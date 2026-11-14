"""MongoDB Atlas client, $jsonSchema enforcement, indexes, Vector Search, and Change Streams."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import CollectionInvalid, OperationFailure, PyMongoError
from pymongo.operations import SearchIndexModel

from mongodb_hackathon.config import Settings, get_settings
from mongodb_hackathon.embeddings import embed_text
from mongodb_hackathon.models import (
    DemoRepo,
    ExperienceMemory,
    JobRun,
    ServiceEvent,
    StepCheckpoint,
    StepStatus,
    utc_now,
)

VECTOR_INDEX_NAME = "experience_vector_idx"


def _search_index_has_filter(idx_doc: Mapping[str, Any], field_path: str) -> bool:
    """Return True if an Atlas Search index definition already indexes `field_path`."""
    for def_key in ("latestDefinition", "definition"):
        defn = idx_doc.get(def_key)
        if isinstance(defn, Mapping):
            fields = defn.get("fields", [])
            if isinstance(fields, list) and any(
                isinstance(f, Mapping) and f.get("path") == field_path for f in fields
            ):
                return True
    return False

STEP_CHECKPOINT_VALIDATOR: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "run_id",
            "step_key",
            "step_seq",
            "idempotency_key",
            "status",
            "attempts",
        ],
        "properties": {
            "run_id": {"bsonType": "string", "minLength": 1},
            "step_key": {"bsonType": "string", "minLength": 1},
            "step_seq": {"bsonType": "int", "minimum": 1},
            "idempotency_key": {"bsonType": "string", "minLength": 1},
            "status": {
                "enum": [s.value for s in StepStatus],
            },
            "attempts": {"bsonType": "int", "minimum": 0},
            "took_effect": {"bsonType": "bool"},
        },
    }
}


class MongoStore:
    """Reusable AsyncMongoClient wrapper for FinishLine state, checkpoints, and Vector Search."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: AsyncMongoClient[dict[str, Any]] | None = None

    @property
    def client(self) -> AsyncMongoClient[dict[str, Any]]:
        """Lazily initialize one shared AsyncMongoClient with bounded pool settings."""
        if self._client is None:
            if not self.settings.mongodb_uri:
                raise RuntimeError("MONGODB_URI is not configured")
            # Long-running FastAPI + worker app: keep a modest pool and fail fast on selection
            self._client = AsyncMongoClient(
                self.settings.mongodb_uri,
                maxPoolSize=25,
                minPoolSize=2,
                connectTimeoutMS=10000,
                socketTimeoutMS=30000,
                serverSelectionTimeoutMS=5000,
            )
        return self._client

    @property
    def db(self) -> AsyncDatabase[dict[str, Any]]:
        return self.client[self.settings.mongodb_db]

    @property
    def runs(self) -> AsyncCollection[dict[str, Any]]:
        return self.db["job_runs"]

    @property
    def checkpoints(self) -> AsyncCollection[dict[str, Any]]:
        return self.db["step_checkpoints"]

    @property
    def memories(self) -> AsyncCollection[dict[str, Any]]:
        return self.db["experience_memories"]

    @property
    def events(self) -> AsyncCollection[dict[str, Any]]:
        return self.db["service_events"]

    @property
    def repos(self) -> AsyncCollection[dict[str, Any]]:
        return self.db["demo_repos"]

    @property
    def infra_cache(self) -> AsyncCollection[dict[str, Any]]:
        return self.db["infra_context_cache"]

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def ensure_schema_and_indexes(self) -> dict[str, Any]:
        """Create collections, $jsonSchema validator, standard/TTL indexes, and Vector Search index."""
        existing = await self.db.list_collection_names()

        if "step_checkpoints" not in existing:
            try:
                await self.db.create_collection(
                    "step_checkpoints",
                    validator=STEP_CHECKPOINT_VALIDATOR,
                    validationLevel="strict",
                    validationAction="error",
                )
            except CollectionInvalid:
                pass
        else:
            await self.db.command(
                {
                    "collMod": "step_checkpoints",
                    "validator": STEP_CHECKPOINT_VALIDATOR,
                    "validationLevel": "strict",
                    "validationAction": "error",
                }
            )

        await self.runs.create_index([("run_id", ASCENDING)], unique=True)
        await self.runs.create_index([("created_at", DESCENDING)])

        await self.checkpoints.create_index(
            [("run_id", ASCENDING), ("step_key", ASCENDING)],
            unique=True,
        )
        await self.checkpoints.create_index(
            [("idempotency_key", ASCENDING)], unique=True
        )

        await self.memories.create_index([("memory_id", ASCENDING)], unique=True)
        await self.memories.create_index([("kind", ASCENDING), ("status", ASCENDING)])
        await self.memories.create_index(
            [("source_repo", ASCENDING), ("created_at", DESCENDING)]
        )

        await self.repos.create_index([("repo", ASCENDING)], unique=True)

        await self.events.create_index(
            [("run_id", ASCENDING), ("created_at", ASCENDING)]
        )
        # Auto-expire operational trace events after expires_at
        await self.events.create_index(
            [("expires_at", ASCENDING)], expireAfterSeconds=0
        )

        vector_definition: dict[str, Any] = {
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": self.settings.embedding_dimensions,
                    "similarity": "dotProduct",
                },
                {"type": "filter", "path": "kind"},
                {"type": "filter", "path": "status"},
                {"type": "filter", "path": "source_repo"},
            ]
        }
        model = SearchIndexModel(
            definition=vector_definition,
            name=VECTOR_INDEX_NAME,
            type="vectorSearch",
        )

        vector_status = "already_exists"
        try:
            existing_search = [
                idx async for idx in await self.memories.list_search_indexes()
            ]
            existing_idx = next(
                (idx for idx in existing_search if idx.get("name") == VECTOR_INDEX_NAME),
                None,
            )
            if existing_idx is None:
                await self.memories.create_search_index(model=model)
                vector_status = "created"
            elif not _search_index_has_filter(existing_idx, "source_repo"):
                await self.memories.update_search_index(
                    VECTOR_INDEX_NAME, vector_definition
                )
                vector_status = "updated"
        except OperationFailure as exc:
            vector_status = f"skipped:{exc.code}"

        return {
            "collections": await self.db.list_collection_names(),
            "vector_index": vector_status,
        }

    async def create_run(self, run: JobRun) -> None:
        await self.runs.insert_one(run.model_dump(mode="python"))

    async def get_run(self, run_id: str) -> JobRun | None:
        doc = await self.runs.find_one({"run_id": run_id}, {"_id": 0})
        return JobRun.model_validate(doc) if doc else None

    async def list_runs(self, limit: int = 15) -> list[JobRun]:
        cursor = (
            self.runs.find({}, {"_id": 0}).sort("created_at", DESCENDING).limit(limit)
        )
        return [JobRun.model_validate(doc) async for doc in cursor]

    async def update_run(self, run_id: str, **fields: Any) -> None:
        fields["updated_at"] = utc_now()
        await self.runs.update_one({"run_id": run_id}, {"$set": fields})

    async def upsert_checkpoint_atomic(
        self,
        checkpoint: StepCheckpoint,
        run_step: int | None = None,
    ) -> None:
        """Persist checkpoint and optionally advance job_runs.current_step in one ACID transaction."""
        payload = checkpoint.model_dump(mode="python")
        payload["updated_at"] = utc_now()

        async with (
            self.client.start_session() as session,
            await session.start_transaction(),
        ):
            await self.checkpoints.update_one(
                {"run_id": checkpoint.run_id, "step_key": checkpoint.step_key},
                {"$set": payload},
                upsert=True,
                session=session,
            )
            if run_step is not None:
                await self.runs.update_one(
                    {"run_id": checkpoint.run_id},
                    {"$set": {"current_step": run_step, "updated_at": utc_now()}},
                    session=session,
                )

    async def get_checkpoints(self, run_id: str) -> list[StepCheckpoint]:
        cursor = self.checkpoints.find({"run_id": run_id}, {"_id": 0}).sort(
            "step_seq", ASCENDING
        )
        return [StepCheckpoint.model_validate(doc) async for doc in cursor]

    async def get_checkpoint(self, run_id: str, step_key: str) -> StepCheckpoint | None:
        doc = await self.checkpoints.find_one(
            {"run_id": run_id, "step_key": step_key},
            {"_id": 0},
        )
        return StepCheckpoint.model_validate(doc) if doc else None

    async def emit_event(
        self,
        run_id: str,
        step_key: str,
        event_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = ServiceEvent(
            run_id=run_id,
            step_key=step_key,
            event_type=event_type,
            message=message,
            details=details or {},
        )
        await self.events.insert_one(event.model_dump(mode="python"))

    async def list_events(self, run_id: str, limit: int = 60) -> list[ServiceEvent]:
        cursor = (
            self.events.find({"run_id": run_id}, {"_id": 0})
            .sort("created_at", DESCENDING)
            .limit(limit)
        )
        items = [ServiceEvent.model_validate(doc) async for doc in cursor]
        items.reverse()
        return items

    async def list_repos(self) -> list[DemoRepo]:
        """Return curated repositories registered in MongoDB Atlas `demo_repos`."""
        cursor = self.repos.find({}, {"_id": 0}).sort("created_at", ASCENDING)
        return [DemoRepo.model_validate(doc) async for doc in cursor]

    async def upsert_repo(self, repo: DemoRepo) -> DemoRepo:
        """Insert or update a curated repository entry in `demo_repos`."""
        payload = repo.model_dump(mode="python")
        created_at = payload.pop("created_at", utc_now())
        await self.repos.update_one(
            {"repo": repo.repo},
            {"$set": payload, "$setOnInsert": {"created_at": created_at}},
            upsert=True,
        )
        doc = await self.repos.find_one({"repo": repo.repo}, {"_id": 0})
        return DemoRepo.model_validate(doc) if doc else repo

    async def upsert_memory(self, mem: ExperienceMemory) -> ExperienceMemory:
        """Insert or update an ExperienceMemory document by `memory_id`."""
        await self.memories.update_one(
            {"memory_id": mem.memory_id},
            {"$set": mem.model_dump(mode="python")},
            upsert=True,
        )
        return mem

    async def list_memories(
        self,
        source_repo: str | None = None,
        limit: int = 40,
        include_global: bool = False,
    ) -> list[dict[str, Any]]:
        """List experience memories (without raw embedding vectors), newest first."""
        query: dict[str, Any] = {}
        if source_repo:
            if include_global:
                query["source_repo"] = {"$in": list(dict.fromkeys([source_repo, "*"]))}
            else:
                query["source_repo"] = source_repo
        return (
            await self.memories.find(query, {"_id": 0, "embedding": 0})
            .sort("created_at", DESCENDING)
            .to_list(length=limit)
        )

    async def search_experience(
        self,
        query: str,
        kind: str | list[str] | None = None,
        limit: int = 4,
        source_repo: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query Atlas Vector Search with active-status and source_repo pre-filters, with dot-product fallback."""
        query_vector = await embed_text(query, self.settings)
        pre_filter: dict[str, Any] = {"status": "active"}
        if isinstance(kind, list):
            if kind:
                pre_filter["kind"] = {"$in": kind}
        elif kind:
            pre_filter["kind"] = kind
        if source_repo:
            pre_filter["source_repo"] = {
                "$in": list(dict.fromkeys([source_repo, "*"]))
            }

        pipeline: list[dict[str, Any]] = [
            {
                "$vectorSearch": {
                    "index": VECTOR_INDEX_NAME,
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": 40,
                    "limit": limit,
                    "filter": pre_filter,
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "memory_id": 1,
                    "kind": 1,
                    "source_repo": 1,
                    "title": 1,
                    "content": 1,
                    "resolution": 1,
                    "field_mapping": 1,
                    "status": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        try:
            cursor = await self.memories.aggregate(pipeline)
            results = [doc async for doc in cursor]
            if results:
                return results
        except OperationFailure:
            pass

        # Fallback if search index is still warming up or updating
        docs = await self.memories.find(pre_filter, {"_id": 0}).to_list(length=500)
        scored: list[tuple[float, dict[str, Any]]] = []
        for doc in docs:
            emb = doc.get("embedding", [])
            if len(emb) == len(query_vector):
                score = sum(a * b for a, b in zip(query_vector, emb, strict=True))
                clean = {k: v for k, v in doc.items() if k != "embedding"}
                clean["score"] = round(float(score), 4)
                scored.append((float(score), clean))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    async def invalidate_memory(self, memory_id: str) -> int:
        res = await self.memories.update_one(
            {"memory_id": memory_id},
            {"$set": {"status": "invalidated"}},
        )
        return int(res.modified_count)

    async def watch_run_stream(
        self, run_id: str = ""
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield live Change Stream events for service_events (belonging to run_id or all if empty)."""
        match_spec: dict[str, Any] = {
            "operationType": {"$in": ["insert", "update", "replace"]}
        }
        if run_id.strip():
            match_spec["fullDocument.run_id"] = run_id.strip()

        pipeline = [{"$match": match_spec}]
        async with await self.events.watch(
            pipeline, full_document="updateLookup"
        ) as stream:
            async for change in stream:
                doc = change.get("fullDocument")
                if doc:
                    doc.pop("_id", None)
                    yield doc

    async def get_cached_infra_context(
        self, repo: str, ref: str = "", ttl_seconds: int = 300
    ) -> tuple[list[str], dict[str, str]] | None:
        """Return cached (repo_files, file_contents) if fresh, else None."""
        try:
            doc = await self.infra_cache.find_one(
                {"repo": repo, "ref": ref}, {"_id": 0}
            )
        except PyMongoError:
            return None
        if not doc:
            return None
        cached_at = doc.get("cached_at")
        if not isinstance(cached_at, datetime):
            return None
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=UTC)
        if utc_now() - cached_at > timedelta(seconds=ttl_seconds):
            return None
        files = doc.get("files")
        contents = doc.get("contents")
        if not isinstance(files, list) or not isinstance(contents, dict):
            return None
        return [str(f) for f in files], {
            str(k): str(v) for k, v in contents.items()
        }

    async def set_cached_infra_context(
        self, repo: str, files: list[str], contents: dict[str, str], ref: str = ""
    ) -> None:
        """Persist discovered repo layout and config contents in MongoDB for cross-worker reuse."""
        try:
            await self.infra_cache.update_one(
                {"repo": repo, "ref": ref},
                {
                    "$set": {
                        "repo": repo,
                        "ref": ref,
                        "files": files,
                        "contents": contents,
                        "cached_at": utc_now(),
                    }
                },
                upsert=True,
            )
        except PyMongoError:
            return
