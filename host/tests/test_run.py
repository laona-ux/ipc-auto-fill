# -*- coding: utf-8 -*-
"""run.py 的纯逻辑单元测试（stdlib-only，含本次完善项回归与新增功能验证）。
运行： python -m unittest discover -s tests -v   （在 host/ 目录下）
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

HOST = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HOST not in sys.path:
    sys.path.insert(0, HOST)

import run


class FakeLink:
    """记录 send 调用、可配置应答的假串口。"""
    def __init__(self, responses=None):
        self.sent = []
        self.responses = responses or {}
        self.closed = False

    def send(self, cmd, timeout=None):
        self.sent.append(cmd)
        key = cmd.get("op")
        if key in self.responses:
            return self.responses[key]
        return {"ack": "ok", "op": key}

    def ping(self):
        return True

    def close(self):
        self.closed = True


def make_cfg(**kw):
    base = {
        "com_port": "COM3", "baudrate": 115200, "data_file": "values.xlsx",
        "sheet": "", "header_row": 0, "has_header": True,
        "row_start": 1, "row_end": 0, "confirm": "none", "start_home": False,
        "step_delay_ms": 0,
        "steps": [{"type": "input", "col": "A", "name": "A", "enter": False}],
        "buttons": {},
    }
    base.update(kw)
    return base


class TempDirCase(unittest.TestCase):
    """把断点/审计重定向到临时目录，避免污染 host/。"""
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="ipc_test_")
        self._old_prog = run.PROGRESS_FILE
        self._old_audit = run.AUDIT_DIR
        run.PROGRESS_FILE = os.path.join(self._tmp, ".progress")
        run.AUDIT_DIR = os.path.join(self._tmp, "audit")

    def tearDown(self):
        run.PROGRESS_FILE = self._old_prog
        run.AUDIT_DIR = self._old_audit
        shutil.rmtree(self._tmp, ignore_errors=True)


# ---------------- 表格解析 ----------------

class TestRowsToRecords(unittest.TestCase):
    def test_header_mode(self):
        rows = [("h1", "h2"), ("1", "2"), ("3", "4"), (None, None)]
        h, recs = run._rows_to_records(rows, 0, True)
        self.assertEqual(h, ["h1", "h2"])
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["h1"], "1")

    def test_no_header_auto_columns(self):
        rows = [("a", "b"), ("1", "2")]
        h, recs = run._rows_to_records(rows, 0, False)
        self.assertEqual(h, ["col1", "col2"])
        self.assertEqual(recs[0]["col1"], "a")

    def test_skip_all_empty_rows(self):
        rows = [("h",), ("1",), (None,), ("2",)]
        h, recs = run._rows_to_records(rows, 0, True)
        self.assertEqual([r["h"] for r in recs], ["1", "2"])

    def test_header_row_out_of_range(self):
        with self.assertRaises(ValueError):
            run._rows_to_records([("a",)], 5, True)


# ---------------- 值格式化 ----------------

class TestFmtValue(unittest.TestCase):
    def test_int_float(self):
        self.assertEqual(run.fmt_value(1500.0), "1500")
        self.assertEqual(run.fmt_value(25.5), "25.5")

    def test_round(self):
        self.assertEqual(run.fmt_value(6.140547, 2), "6.14")

    def test_bool_and_none(self):
        self.assertEqual(run.fmt_value(True), "1")
        self.assertIsNone(run.fmt_value(None))

    def test_text_not_rounded(self):
        # 文本数字原本不做 round（保持原样）
        self.assertEqual(run.fmt_value("6.1405", 2), "6.1405")


# ---------------- 步骤展开 ----------------

class TestExpandSteps(unittest.TestCase):
    def test_button_expansion(self):
        cfg = make_cfg(steps=[{"type": "button", "name": "b"}],
                       buttons={"b": [{"type": "key", "key": "enter"}]})
        steps = run.expand_steps(cfg)
        self.assertEqual(steps, [{"type": "key", "key": "enter"}])

    def test_cycle_guard(self):
        cfg = make_cfg(steps=[{"type": "button", "name": "b"}],
                       buttons={"b": [{"type": "button", "name": "b"}]})
        steps = run.expand_steps(cfg)
        # 循环引用应保留引用而不死循环
        self.assertEqual(steps, [{"type": "button", "name": "b"}])

    def test_targets_compat(self):
        cfg = {"targets": [{"mode": "mouse", "x": 10, "y": 20, "col": "A",
                            "round": None, "name": "点A"}]}
        steps = run.expand_steps(cfg)
        self.assertEqual(steps[0]["type"], "click")
        self.assertEqual(steps[-1]["type"], "input")


# ---------------- 指令生成 / 安全加固 ----------------

class TestStepCmds(unittest.TestCase):
    def test_click(self):
        cmds = run._step_cmds({"type": "click", "x": 10, "y": 20}, {}, 0)
        self.assertEqual(cmds[0], {"op": "click_at", "x": 10, "y": 20})

    def test_type_sanitize_control_chars(self):
        # \n \t 会被固件转成真实回车/Tab，必须被替换为空格
        cmds = run._step_cmds({"type": "input", "value": "25.5\n1.2\t3",
                               "enter": False}, {}, 0)
        type_cmd = [c for c in cmds if c["op"] == "type"][0]
        self.assertNotIn("\n", type_cmd["text"])
        self.assertNotIn("\t", type_cmd["text"])
        self.assertEqual(type_cmd["text"], "25.5 1.2 3")

    def test_type_len_cap(self):
        cmds = run._step_cmds({"type": "input", "value": "x" * 500}, {}, 0)
        type_cmd = [c for c in cmds if c["op"] == "type"][0]
        self.assertLessEqual(len(type_cmd["text"]), run.MAX_TYPE_LEN)

    def test_key_whitelist_rejects_win(self):
        with self.assertRaises(ValueError):
            run._step_cmds({"type": "key", "key": "win+r"}, {}, 0)
        with self.assertRaises(ValueError):
            run._step_cmds({"type": "key", "key": "alt+f4"}, {}, 0)

    def test_key_whitelist_allows_safe(self):
        cmds = run._step_cmds({"type": "key", "key": "enter"}, {}, 0)
        self.assertEqual(cmds[0], {"op": "key", "key": "enter"})
        cmds = run._step_cmds({"type": "key", "key": "ctrl+a"}, {}, 0)
        self.assertEqual(cmds[0]["key"], "ctrl+a")

    def test_pre_keys_validated(self):
        with self.assertRaises(ValueError):
            run._step_cmds({"type": "input", "value": "1", "pre_keys": ["win+x"]}, {}, 0)


class TestValidateKey(unittest.TestCase):
    def test_safe(self):
        for k in ("enter", "tab", "f5", "ctrl+a", "up", "a", "1"):
            ok, _ = run.validate_key(k)
            self.assertTrue(ok, k)

    def test_unsafe(self):
        for k in ("win+r", "win", "alt+f4", "lwin", "cmd"):
            ok, why = run.validate_key(k)
            self.assertFalse(ok, k)
            self.assertTrue(why)


# ---------------- 断点指纹 / 配置漂移 ----------------

class TestProgressDigest(TempDirCase):
    def setUp(self):
        super().setUp()
        # 造一个真实的临时数据文件，让 _cfg_digest 引用稳定
        self._data = os.path.join(self._tmp, "values.xlsx")
        with open(self._data, "w", encoding="utf-8") as f:
            f.write("dummy")

    def test_digest_stable_and_sensitive(self):
        c1 = make_cfg()
        c2 = make_cfg()
        self.assertEqual(run._cfg_digest(c1), run._cfg_digest(c2))
        c3 = make_cfg(steps=[{"type": "input", "col": "B"}])
        self.assertNotEqual(run._cfg_digest(c1), run._cfg_digest(c3))

    def test_progress_drift_detected(self):
        c1 = make_cfg()
        run.save_progress(3, 10, c1["data_file"], digest=run._cfg_digest(c1))
        prog = run.load_progress()
        self.assertFalse(run.progress_is_drifted(prog, c1))
        c2 = make_cfg(steps=[{"type": "input", "col": "C"}])
        self.assertTrue(run.progress_is_drifted(prog, c2))

    def test_old_progress_without_digest_not_blocked(self):
        run.save_progress(3, 10, "values.xlsx")  # 旧格式无 digest
        prog = run.load_progress()
        self.assertFalse(run.progress_is_drifted(prog, make_cfg()))

    def test_save_load_roundtrip(self):
        run.save_progress(5, 10, "v.xlsx", digest="abc123")
        prog = run.load_progress()
        self.assertEqual(prog["row"], 5)
        self.assertEqual(prog["steps_digest"], "abc123")


# ---------------- run_once：确认后才存断点（H1 回归）+ 审计 ----------------

class TestRunOnceConfirmOrdering(TempDirCase):
    def test_no_progress_saved_if_user_quits_at_confirm(self):
        # H1 回归：断点必须在“人工确认通过之后”才保存。
        # 第一行在行确认处抛 UserQuit → 该行不得被记为完成。
        cfg = make_cfg(confirm="enter",
                       steps=[{"type": "input", "col": "A", "name": "A"}])
        records = [{"A": 1}, {"A": 2}]

        def confirm_fn(prompt):
            raise run.UserQuit("quit")

        link = FakeLink()
        with self.assertRaises(run.UserQuit):
            run.run_once(link, cfg, records, 0, confirm_fn=confirm_fn,
                         header=["A"])
        # 断点文件不应包含第一行（未被确认，不得续传跳过）
        prog = run.load_progress()
        self.assertIsNone(prog, "未确认的行不应写断点")

    def test_dry_run_writes_audit_not_progress(self):
        cfg = make_cfg()
        records = [{"A": 1}, {"A": 2}]
        link = FakeLink()
        run.run_once(link, cfg, records, 0, dry_run=True, header=["A"])
        # dry run 不应发送指令、不应写断点
        self.assertEqual(link.sent, [])
        self.assertIsNone(run.load_progress())
        # 但应写审计
        import glob
        logs = glob.glob(os.path.join(run.AUDIT_DIR, "*.jsonl"))
        self.assertTrue(logs, "dry-run 应产生审计日志")

    def test_success_saves_progress_and_audit(self):
        cfg = make_cfg(confirm="none", steps=[{"type": "input", "col": "A", "name": "A"}])
        records = [{"A": 1}, {"A": 2}]
        link = FakeLink()
        run.run_once(link, cfg, records, 0, header=["A"])
        prog = run.load_progress()
        self.assertEqual(prog["row"], 2)
        self.assertIn("steps_digest", prog)
        import glob
        logs = glob.glob(os.path.join(run.AUDIT_DIR, "*.jsonl"))
        self.assertTrue(logs)
        with open(logs[0], encoding="utf-8") as f:
            lines = [json.loads(x) for x in f if x.strip()]
        self.assertEqual(len([l for l in lines if l["status"] == "filled"]), 2)


# ---------------- 配置校验 ----------------

class TestValidateConfig(unittest.TestCase):
    def test_valid(self):
        cfg = make_cfg(steps=[{"type": "click", "x": 1, "y": 2}])
        self.assertEqual(run.validate_config(cfg, header=["A"]), [])

    def test_unknown_step_type(self):
        cfg = make_cfg(steps=[{"type": "weird"}])
        self.assertTrue(any("未知步骤类型" in p for p in run.validate_config(cfg)))

    def test_missing_button(self):
        cfg = make_cfg(steps=[{"type": "button", "name": "nope"}], buttons={})
        self.assertTrue(any("不存在" in p for p in run.validate_config(cfg)))

    def test_bad_key(self):
        cfg = make_cfg(steps=[{"type": "key", "key": "win+r"}])
        self.assertTrue(any("win" in p.lower() or "白名单" in p for p in run.validate_config(cfg)))

    def test_int_col_in_range(self):
        # 整数列号在范围内 → 合法
        cfg = make_cfg(steps=[{"type": "input", "col": 0}])
        self.assertEqual(run.validate_config(cfg, header=["A", "B"]), [])

    def test_int_col_out_of_range(self):
        cfg = make_cfg(steps=[{"type": "input", "col": 9}])
        self.assertTrue(any("越界" in p or "范围" in p for p in run.validate_config(cfg, header=["A"])))

    def test_nonnumeric_coord(self):
        cfg = make_cfg(steps=[{"type": "click", "x": "abc", "y": 1}])
        self.assertTrue(any("x" in p for p in run.validate_config(cfg)))

    def test_bad_confirm(self):
        cfg = make_cfg(confirm="always")
        self.assertTrue(any("confirm" in p for p in run.validate_config(cfg)))