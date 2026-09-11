"""REST API over the workflow engine."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from eudr.config import settings
from eudr.models import Verdict
from eudr.tools.alerts.monitor import push_alert
from eudr.workflow import engine

app = FastAPI(title="EUDR Agent", version="0.1.0")
WEB = Path(__file__).resolve().parents[1] / "web"
app.mount("/app/static", StaticFiles(directory=WEB / "static"), name="static")


@app.get("/")
def root():
    return RedirectResponse("/app")


@app.get("/app")
@app.get("/app/{path:path}")
def console(path: str = ""):
    return FileResponse(WEB / "index.html")


class CreateCase(BaseModel):
    folder: str
    operator: str | None = None
    use_agent: bool | None = None
    run: bool = False


class ReviewAction(BaseModel):
    reviewer: str
    note: str = ""


class OverrideAction(BaseModel):
    reviewer: str
    verdict: Verdict
    reason: str


class AckAction(BaseModel):
    reviewer: str
    acknowledge_critic: bool = False


class Alert(BaseModel):
    plot_id: str
    source: str
    area_ha: float
    date: str | None = None


@app.get("/cases")
def list_cases(status: str | None = None):
    return engine.store().list(status)


@app.post("/cases")
def create_case(body: CreateCase, bg: BackgroundTasks):
    if not Path(body.folder).is_dir():
        raise HTTPException(400, "folder not found")
    c = engine.create_case(body.folder, body.operator, body.use_agent)
    if body.run:
        bg.add_task(engine.run_background, c.id, True)
    return engine.summary(c.id)


@app.post("/cases/upload")
async def create_case_upload(files: list[UploadFile], bg: BackgroundTasks, operator: str | None = None, use_agent: bool = True, run: bool = True):
    d = Path(tempfile.mkdtemp(prefix="eudr_upload_", dir=settings.data_dir / "uploads"))
    for f in files:
        with open(d / Path(f.filename).name, "wb") as out:
            shutil.copyfileobj(f.file, out)
    c = engine.create_case(d, operator, use_agent)
    if run:
        bg.add_task(engine.run_background, c.id, True)
    return engine.summary(c.id)


@app.get("/cases/{case_id}")
def get_case(case_id: str):
    try:
        return engine.summary(case_id)
    except KeyError:
        raise HTTPException(404, "case not found")


@app.post("/cases/{case_id}/run")
def run_case(case_id: str, bg: BackgroundTasks, imagery: bool = True, background: bool = False):
    if background:
        bg.add_task(engine.run_background, case_id, imagery)
        return {"case": case_id, "started": True}
    return engine.run(case_id, with_imagery=imagery)


@app.get("/cases/{case_id}/progress")
def progress(case_id: str):
    return engine.progress(case_id)


@app.get("/cases/{case_id}/geojson")
def geojson(case_id: str):
    return engine.geojson(case_id)


@app.get("/dashboard")
def dashboard():
    return engine.dashboard()


@app.get("/cases/{case_id}/pages/{name}")
def page_image(case_id: str, name: str):
    p = settings.data_dir / "cases" / case_id / "docs" / "pages" / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.post("/cases/{case_id}/redraft")
def redraft(case_id: str):
    return engine.redraft(case_id)


@app.get("/cases/{case_id}/plots/{plot_id}")
def explain(case_id: str, plot_id: str):
    return engine.explain_plot(case_id, plot_id)


@app.get("/cases/{case_id}/review")
def review(case_id: str):
    return engine.review_queue(case_id)


@app.post("/cases/{case_id}/assessments/{aid}/approve")
def approve(case_id: str, aid: str, body: ReviewAction):
    return engine.approve(case_id, aid, body.reviewer, body.note)


@app.post("/cases/{case_id}/assessments/{aid}/override")
def override(case_id: str, aid: str, body: OverrideAction):
    try:
        return engine.override(case_id, aid, body.verdict, body.reason, body.reviewer)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/cases/{case_id}/acknowledge")
def acknowledge(case_id: str, body: AckAction):
    try:
        return engine.summary(engine.acknowledge(case_id, body.reviewer, body.acknowledge_critic).id)
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/cases/{case_id}/monitor")
def monitor(case_id: str):
    return engine.monitor(case_id)


@app.get("/cases/{case_id}/dossier")
def dossier(case_id: str):
    c = engine.store().get(case_id)
    if not c.dossier or not c.dossier.evidence_pack_path:
        raise HTTPException(404, "no dossier yet")
    return FileResponse(c.dossier.evidence_pack_path, media_type="application/pdf", filename=f"{case_id}_evidence_pack.pdf")


@app.get("/cases/{case_id}/dds")
def dds(case_id: str):
    c = engine.store().get(case_id)
    return c.dossier.dds_payload if c.dossier else {}


@app.get("/cases/{case_id}/documents")
def documents(case_id: str):
    c = engine.store().get(case_id)
    return [{**d.model_dump(mode="json"), "file": Path(d.path).name} for d in c.documents]


@app.get("/cases/{case_id}/trace")
def trace(case_id: str):
    c = engine.store().get(case_id)
    return c.trace.model_dump(mode="json") if c.trace else None


@app.get("/cases/{case_id}/exceptions")
def exceptions(case_id: str):
    return engine.exceptions(case_id)


@app.get("/cases/{case_id}/exceptions.csv")
def exceptions_csv(case_id: str):
    p = settings.data_dir / "cases" / case_id / "exception_ledger.csv"
    if not p.exists():
        raise HTTPException(404, "no exception ledger yet")
    return FileResponse(p, media_type="text/csv", filename=f"{case_id}_exceptions.csv")


@app.get("/cases/{case_id}/citations/{name}")
def citation_image(case_id: str, name: str):
    p = settings.data_dir / "cases" / case_id / "docs" / "citations" / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/reports/roi")
def roi():
    return engine.roi_report()


@app.get("/cases/{case_id}/ledger")
def ledger(case_id: str, n: int = 50):
    return engine.ledger_tail(case_id, n)


@app.get("/cases/{case_id}/evidence/{plot_id}/{name}")
def evidence(case_id: str, plot_id: str, name: str):
    p = settings.data_dir / "cases" / case_id / "evidence" / plot_id / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.post("/alerts")
def alert(a: Alert):
    push_alert(a.plot_id, a.source, a.area_ha, a.date)
    return {"ok": True}
