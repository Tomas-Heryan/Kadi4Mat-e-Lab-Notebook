"""Offline and end-to-end tests.

Run:  python -m unittest discover -s tests -v
The end-to-end tests start the HTTPS mock server (tests/mock_kadi.py); no real Kadi4Mat
instance and no real token are needed.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from kadi_lab_manager import cli  # noqa: E402
from kadi_lab_manager.compile import compile_model, kadi_checksum  # noqa: E402
from kadi_lab_manager.errors import ModelError  # noqa: E402
from kadi_lab_manager.extras import ExtrasValidationError, load_extras  # noqa: E402
from kadi_lab_manager.model import load_model  # noqa: E402
from mock_kadi import MockKadiServer, MockState  # noqa: E402

MODEL_CEET = ROOT / "model" / "ceet.yaml"
MODEL_DEMO = ROOT / "model" / "demo.yaml"


class OfflineTests(unittest.TestCase):
    def test_structure_model_compiles(self):
        compiled = compile_model(load_model(MODEL_CEET))
        stats = compiled.stats()
        self.assertEqual(stats["records"], 0)
        self.assertGreaterEqual(stats["templates"], 60)
        self.assertEqual(stats["collections"], 10)

    def test_demo_model_compiles(self):
        compiled = compile_model(load_model(MODEL_DEMO))
        stats = compiled.stats()
        self.assertEqual(stats["records"], 46)
        self.assertEqual(stats["files"], 5)
        self.assertGreater(stats["metadata_values"], 1000)
        # namespace applied everywhere, including identifier-valued strings
        rec = next(r for r in compiled.records if r.identifier == "prep-spe-photocat-r01-2026-08-04-demo")
        protocol = next(e for e in rec.payload["extras"] if e["key"] == "protocol")
        self.assertEqual(protocol["value"][0]["value"], "meth-spe-pharma-v03-demo")

    def test_server_rules_are_enforced_offline(self):
        with self.assertRaises(ExtrasValidationError):
            load_extras([{"key": "d", "type": "date", "value": "2026-08-04"}])          # bare date
        with self.assertRaises(ExtrasValidationError):
            load_extras([{"key": "n", "type": "int", "value": True}])                     # bool is not int
        with self.assertRaises(ExtrasValidationError):
            load_extras([{"key": "s", "type": "str", "value": "x", "unit": "mg"}])        # unit on str
        out = load_extras([{"key": "x", "type": "float", "value": 5, "unit": " mL "}])
        self.assertEqual(out, [{"key": "x", "type": "float", "unit": "mL", "value": 5.0}])

    def test_model_errors_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.yaml"
            bad.write_text(
                "schema_version: 1\nvocab:\n  link_types:\n    used: {term: http://www.w3.org/ns/prov#used}\n"
                "templates:\n  - identifier: tmpl-x\n    kind: record\n    title: X\n    record: {type: sample}\n"
                "    fields:\n      - {key: n, type: int, unit: mg, options: [1, 2]}\n"
                "records:\n  - identifier: Bad Id\n    title: ''\n    template: tmpl-x\n    values: {n: 3, typo: 1}\n"
                "links:\n  - {source: bad-id, target: bad-id, type: nope}\n", encoding="utf-8")
            with self.assertRaises(ModelError) as ctx:
                compile_model(load_model(bad))
            text = "\n".join(ctx.exception.problems)
            self.assertIn("identifier 'Bad Id' must match", text)
            self.assertIn("empty title", text)
            self.assertIn("not in vocab.link_types", text)
            self.assertIn("link from 'bad-id' to itself", text)

    def test_kadi_checksum_direct_and_chunked(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "f.bin"
            p.write_bytes(b"a" * 1000)
            self.assertEqual(len(kadi_checksum(p)), 32)
            self.assertTrue(kadi_checksum(p, boundary=100, chunk_size=300).endswith("-4"))


class EndToEndTests(unittest.TestCase):
    """Full lifecycle against the TLS mock: plan -> apply -> idempotent re-run -> drift ->
    update -> snapshot -> export -> import -> cleanup."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="klm-e2e-"))
        cls.state = MockState(groups={"ceet-data-stewards": 10, "ceet-lab-staff": 11})
        cls.server = MockKadiServer(state=cls.state).__enter__()
        os.environ.update({
            "KADI_URL": cls.server.url,
            "KADI_TOKEN": "mock-token-0123456789",
            "KADI_CA_BUNDLE": cls.server.ca_bundle,
            "KADI_STATE_DIR": str(cls.tmp / "state"),
            "KADI_REPORT_DIR": str(cls.tmp / "reports"),
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        })
        os.chdir(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)
        os.chdir(ROOT)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_cli(self, *args) -> int:
        return cli.main([str(a) for a in args])

    def test_lifecycle(self):
        demo = str(MODEL_DEMO)
        with self.subTest("doctor"):
            self.assertEqual(self.run_cli("doctor"), 0)

        with self.subTest("plan on empty instance"):
            self.assertEqual(self.run_cli("plan", demo, "-q"), 0)
            report = self._latest_report("plan")
            ops = report["summary"]["operations"]
            self.assertEqual(ops.get("create:planned"), 11 + 62 + 46)

        with self.subTest("apply"):
            self.assertEqual(self.run_cli("apply", demo, "--yes", "-q"), 0)
            report = self._latest_report("apply")
            self.assertEqual(report["errors"], [])
            ops = report["summary"]["operations"]
            self.assertEqual(ops.get("create:done"), 119)
            self.assertEqual(ops.get("link:done"), 86)
            self.assertEqual(ops.get("upload:done"), 5)
            self.assertEqual(ops.get("add_child:done"), 10)
            self.assertEqual(len(self.state.links), 86)
            # every uploaded file verified by checksum on the server side
            self.assertEqual(len([f for f in self.state.files.values() if f["state"] == "active"]), 5)

        with self.subTest("server state matches the model exactly"):
            rec = self.state.by_identifier("records", "exp-xrd-tio2-c450-2026-07-27-demo")
            compiled = compile_model(load_model(MODEL_DEMO))
            desired = next(r for r in compiled.records if r.identifier == rec["identifier"])
            self.assertEqual(rec["extras"], desired.payload["extras"])
            self.assertEqual(rec["tags"], desired.payload["tags"])
            tmpl = self.state.by_identifier("templates", "tmpl-instrument-demo")
            self.assertEqual(tmpl["data"]["collections"], [self.state.by_identifier("collections", "cat-instruments-demo")["id"]])
            col = self.state.by_identifier("collections", "cat-instruments-demo")
            self.assertEqual(col["parent_id"], self.state.by_identifier("collections", "ceet-demo")["id"])
            self.assertEqual(col["record_template_id"], tmpl["id"])

        with self.subTest("second apply is a no-op"):
            n_requests = len(self.state.requests)
            self.assertEqual(self.run_cli("apply", demo, "--yes", "-q"), 0)
            report = self._latest_report("apply")
            self.assertFalse(any(k.startswith(("create", "link", "upload", "add_")) for k in report["summary"]["operations"]))
            writes = [m for m, _ in self.state.requests[n_requests:] if m in ("POST", "PATCH", "PUT", "DELETE")]
            self.assertEqual(writes, [])

        with self.subTest("drift is detected and fixed only with --update"):
            rec = self.state.by_identifier("records", "smpl-ww-ov-2026-08-03-eff-demo")
            rec["title"] = "edited in the web UI"
            for extra in rec["extras"]:
                if extra["key"] == "volume":
                    extra["value"] = 1.0
            self.assertEqual(self.run_cli("plan", demo, "-q"), 0)
            report = self._latest_report("plan")
            drift = [op for op in report["operations"] if op["action"] == "update"]
            self.assertEqual(len(drift), 1)
            self.assertEqual(sorted(drift[0]["changed"]), ["extras", "title"])
            self.assertEqual(self.run_cli("apply", demo, "--yes", "-q"), 0)      # without --update: untouched
            self.assertEqual(rec["title"], "edited in the web UI")
            self.assertEqual(self.run_cli("apply", demo, "--yes", "--update", "-q"), 0)
            self.assertNotEqual(rec["title"], "edited in the web UI")
            self.assertEqual(next(e["value"] for e in rec["extras"] if e["key"] == "volume"), 10000.0)

        with self.subTest("snapshot reports no drift"):
            code = self.run_cli("snapshot", demo, "--out", str(self.tmp / "snapshots"), "-q")
            self.assertEqual(code, 0)
            manifests = list((self.tmp / "snapshots").glob("*/manifest.json"))
            self.assertEqual(len(manifests), 1)
            manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
            self.assertEqual(manifest["drift"], {})
            self.assertEqual(len(manifest["files"]), 46 + 11 + 62)

        with self.subTest("export json and ro-crate"):
            out = self.tmp / "exports"
            self.assertEqual(self.run_cli("export", "--record", "raw-xrd-tio2-c450-2026-07-27-demo", "--out", str(out)), 0)
            data = json.loads((out / "raw-xrd-tio2-c450-2026-07-27-demo.json").read_text(encoding="utf-8"))
            self.assertEqual([f["name"] for f in data["files"]], ["xrd_tio2-sg-2026-001-c450.xy"])
            self.assertTrue(any("record_to" in l for l in data["links"]))
            self.assertEqual(self.run_cli("export", "--collection", "proj-project-demo",
                                          "--format", "ro-crate", "--out", str(out)), 0)
            crate = out / "proj-project-demo.eln"
            with zipfile.ZipFile(crate) as zf:
                names = zf.namelist()
            self.assertIn("proj-project-demo/ro-crate-metadata.json", names)
            self.assertTrue(any(n.endswith("/files/xrd_tio2-sg-2026-001-c450.xy") for n in names))
            self.assertTrue((out / "proj-project-demo.eln.sha256").exists())

        with self.subTest("import-export round trip"):
            out = self.tmp / "exports"
            self.assertEqual(self.run_cli("export", "--collection", "proj-project-demo", "--out", str(out)), 0)
            yaml_out = self.tmp / "imported.yaml"
            code = self.run_cli("import-export", str(out / "proj-project-demo.json"), "--out", str(yaml_out),
                                "--namespace=-copy", "--download-files", "-q")
            self.assertEqual(code, 0)
            self.assertTrue((self.tmp / "files" / "raw-xrd-tio2-c450-2026-07-27-demo" / "xrd_tio2-sg-2026-001-c450.xy").exists())
            model = load_model(yaml_out)
            compiled = compile_model(model)
            self.assertEqual(len(compiled.records), 26)           # the records in the project collection
            self.assertTrue(all(r.identifier.endswith("-copy") for r in compiled.records))
            self.assertEqual(compiled.stats()["files"], 5)
            # the copy can be deployed next to the original without touching it
            self.assertEqual(self.run_cli("apply", str(yaml_out), "--yes", "-q"), 0)
            self.assertIsNotNone(self.state.by_identifier("records", "exp-xrd-tio2-c450-2026-07-27-demo-copy"))
            copy_rec = self.state.by_identifier("records", "raw-xrd-tio2-c450-2026-07-27-demo-copy")
            orig_rec = self.state.by_identifier("records", "raw-xrd-tio2-c450-2026-07-27-demo")
            # identical metadata; identifier-valued strings carry the new namespace by design
            copy_text = json.dumps(copy_rec["extras"], sort_keys=True).replace("-demo-copy", "-demo")
            self.assertEqual(copy_text, json.dumps(orig_rec["extras"], sort_keys=True))

        with self.subTest("cleanup removes only what the tool created"):
            # an unrelated record that existed before must survive
            with_stranger = {"identifier": "stranger-record", "title": "not ours", "extras": []}
            from kadi_lab_manager.client import KadiClient
            from kadi_lab_manager.config import load_config
            with KadiClient(load_config()) as client:
                client.create("records", with_stranger)
            self.assertEqual(self.run_cli("cleanup", "--namespace=-demo", "-q"), 0)          # dry run
            self.assertIsNotNone(self.state.by_identifier("records", "exp-xrd-tio2-c450-2026-07-27-demo"))
            self.assertEqual(self.run_cli("cleanup", "--namespace=-demo", "--apply", "--yes", "-q"), 0)
            self.assertIsNone(self.state.by_identifier("records", "exp-xrd-tio2-c450-2026-07-27-demo"))
            self.assertIsNone(self.state.by_identifier("collections", "ceet-demo"))
            self.assertIsNotNone(self.state.by_identifier("records", "stranger-record"))
            self.assertEqual(self.run_cli("plan", demo, "-q"), 0)
            report = self._latest_report("plan")
            self.assertEqual(report["summary"]["operations"].get("create:planned"), 119)

    def _latest_report(self, command: str) -> dict:
        reports = sorted((self.tmp / "reports").glob(f"*_{command}_*.json"))
        self.assertTrue(reports, f"no {command} report")
        return json.loads(reports[-1].read_text(encoding="utf-8"))


class ChunkedUploadTests(unittest.TestCase):
    def test_chunked_upload_with_checksums(self):
        tmp = Path(tempfile.mkdtemp(prefix="klm-chunk-"))
        state = MockState(chunk_boundary=64 * 1024, chunk_size=48 * 1024)
        with MockKadiServer(state=state) as server:
            os.environ.update({"KADI_URL": server.url, "KADI_TOKEN": "mock-token-0123456789",
                               "KADI_CA_BUNDLE": server.ca_bundle, "NO_PROXY": "127.0.0.1,localhost",
                               "no_proxy": "127.0.0.1,localhost"})
            from kadi_lab_manager.client import KadiClient
            from kadi_lab_manager.config import load_config
            big = tmp / "big.csv"
            big.write_bytes(os.urandom(200 * 1024 + 123))
            with KadiClient(load_config()) as client:
                rec = client.create("records", {"identifier": "chunk-test", "title": "chunk test", "extras": []})
                meta = client.upload_file(rec["id"], big, "big.csv", mimetype="text/csv")
                self.assertTrue(meta["checksum"].endswith("-5"))
                self.assertEqual(meta["checksum"], kadi_checksum(big, boundary=64 * 1024, chunk_size=48 * 1024))
                # replacing requires replace=True
                from kadi_lab_manager.errors import ApiError
                with self.assertRaises(ApiError):
                    client.upload_file(rec["id"], big, "big.csv", mimetype="text/csv")
                meta2 = client.upload_file(rec["id"], big, "big.csv", mimetype="text/csv", replace=True)
                self.assertEqual(meta2["id"], meta["id"])
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
