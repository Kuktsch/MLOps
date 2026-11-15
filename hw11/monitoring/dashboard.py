import json
from pathlib import Path


root = Path(__file__).resolve().parent
queries = json.loads((root / "promql.json").read_text())
datasource = {"type": "prometheus", "uid": "hw11-prometheus"}
dashboard = {
    "uid": "hw11-inference", "title": "HW 11 / CPU inference", "schemaVersion": 40, "version": 1,
    "refresh": "5s", "time": {"from": "now-30m", "to": "now"}, "panels": [],
}
for index, (title, (unit, expression)) in enumerate(queries.items()):
    dashboard["panels"].append({
        "id": index + 1, "type": "timeseries", "title": title, "datasource": datasource,
        "gridPos": {"h": 8, "w": 12, "x": index % 2 * 12, "y": index // 2 * 8},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "targets": [{"refId": "A", "expr": expression, "legendFormat": "{{pod}} {{outcome}}"}],
    })
(root / "dashboard.json").write_text(json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n")
