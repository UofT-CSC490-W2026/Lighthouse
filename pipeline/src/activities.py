"""Temporal activities for the standalone pipeline worker."""

from typing import Any

from temporalio import activity


@activity.defn(name="ingest_activity")
async def ingest_activity(payload: dict[str, Any]) -> dict[str, Any]:
    return {"stage": "ingest", "ok": True, "payload": payload}


@activity.defn(name="clean_activity")
async def clean_activity(payload: dict[str, Any]) -> dict[str, Any]:
    return {"stage": "clean", "ok": True, "payload": payload}


@activity.defn(name="transform_activity")
async def transform_activity(payload: dict[str, Any]) -> dict[str, Any]:
    return {"stage": "transform", "ok": True, "payload": payload}


@activity.defn(name="store_activity")
async def store_activity(payload: dict[str, Any]) -> dict[str, Any]:
    return {"stage": "store", "ok": True, "payload": payload}


@activity.defn(name="mental_model_activity")
async def mental_model_activity(payload: dict[str, Any]) -> dict[str, Any]:
    return {"stage": "mental_model", "ok": True, "payload": payload}
