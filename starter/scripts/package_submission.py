"""Create a LOCAL full bundle; never include credentials, environments, model cache or Git."""
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import json,sys,zipfile
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.paths import ROOT,read_json,write_json

def main():
    student="2A202603560"
    destination=ROOT/"artifacts/submission"
    destination.mkdir(parents=True,exist_ok=True)
    target=destination/(student+"_TruongVanThong_local_full.zip")
    allowed_dirs=("starter/src","starter/scripts","starter/tests","benchmark","configs","data","docs",
                  "report","results","assets")
    files=set()
    for directory in allowed_dirs:
        for path in (ROOT/directory).rglob("*"):
            if not path.is_file():continue
            relative=path.relative_to(ROOT)
            if any(part in (".git",".venv",".cache","__pycache__",".pytest_cache") for part in relative.parts):continue
            if path.name==".env" or (path.name.startswith(".env.") and path.name!=".env.example"):continue
            files.add(path)
    for relative in ("README.md","STUDENT.md","GUIDE.md","BENCHMARK.md","RULES.md","RUBRIC.md",
                     "CHECKPOINTS.md","SUBMISSION.md","REPORT_TEMPLATE.md",".gitignore",
                     "starter/README.md","starter/requirements.txt","starter/requirements-lock.txt",
                     "starter/docker-compose.yml","starter/init.sql","starter/.env.example",
                     "artifacts/experiment_log.csv","results/review_labels.csv"):
        path=ROOT/relative
        if path.is_file():files.add(path)
    files.add(ROOT/"starter/data/Digital control system.pdf")
    for name in ("strategy_A.npz","strategy_B.npz"):
        files.add(ROOT/"artifacts/embedding_cache"/name)
    inventory=[]
    with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(files,key=lambda p:p.relative_to(ROOT).as_posix()):
            if not path.resolve().is_relative_to(ROOT):raise ValueError("Bundle file outside workspace")
            raw=path.read_bytes()
            relative=path.relative_to(ROOT).as_posix()
            archive.writestr(relative,raw)
            inventory.append({"path":relative,"bytes":len(raw),"sha256":sha256(raw).hexdigest()})
        archive.writestr("LOCAL_BUNDLE_NOTICE.txt",
            "Local bundle includes source material. Redistribution permission has not been verified. "
            "Do not treat this bundle as permission to publish the PDF or source-derived full text. "
            "AI-assisted labels retain their original reviewer provenance.")
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:raise ValueError("ZIP integrity check failed")
        if any(name.endswith("/.env") or "/.git/" in name or "/.venv/" in name for name in archive.namelist()):
            raise ValueError("Private environment accidentally included")
    write_json(destination/"local_bundle_manifest.json",{
        "created_at":datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds"),
        "student_id":student,"bundle":target.relative_to(ROOT).as_posix(),
        "bundle_sha256":sha256(target.read_bytes()).hexdigest(),"bundle_bytes":target.stat().st_size,
        "files":inventory,"publication":"local only; excluded from Git",
        "source_redistribution_permission":"not verified"})
    print("LOCAL BUNDLE OK:",target.relative_to(ROOT).as_posix())
    print("Files:",len(inventory),"| Bytes:",target.stat().st_size)
    print("No .env, Git metadata, environment or model cache included.")

if __name__=="__main__":main()
