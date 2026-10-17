"""对话式修正的纯逻辑测试（不联网：模型调用被替换）。"""
import json

import pytest

from app import project_chat as pc


def _items():
    return [
        {"name": "黑湖垭口", "type_label": "垭口", "kind": "saddle",
         "distance_m": 7, "ele": 4720.0},
        {"name": "杂巴拉垭口", "type_label": "垭口", "kind": "saddle",
         "distance_m": 6, "ele": 4750.0},
        {"name": "万花池牛场", "type_label": "营地", "kind": "camp_site",
         "distance_m": 16, "ele": None},
        {"name": "牛奶海", "type_label": "湖泊", "kind": "water",
         "distance_m": 150, "ele": 4600.0},
    ]


class TestApplyOps:
    def test_drop_poi(self):
        out, applied, rejected = pc.apply_ops(
            _items(), [{"op": "drop_poi", "name": "牛奶海"}])
        assert len(out) == 3
        assert all(i["name"] != "牛奶海" for i in out)
        assert applied and not rejected

    def test_drop_unknown_name_rejected(self):
        out, applied, rejected = pc.apply_ops(
            _items(), [{"op": "drop_poi", "name": "不存在垭口"}])
        assert len(out) == 4
        assert rejected and not applied

    def test_keep_kinds(self):
        out, applied, rejected = pc.apply_ops(
            _items(), [{"op": "keep_kinds", "kinds": ["垭口"]}])
        assert len(out) == 2
        assert all(i["type_label"] == "垭口" for i in out)
        assert not rejected

    def test_keep_kinds_invalid(self):
        out, applied, rejected = pc.apply_ops(
            _items(), [{"op": "keep_kinds", "kinds": ["冰川"]}])
        assert len(out) == 4
        assert rejected

    def test_rename_poi(self):
        out, applied, rejected = pc.apply_ops(
            _items(), [{"op": "rename_poi", "name": "牛奶海", "new_name": "主峰"}])
        assert any(i["name"] == "主峰" for i in out)
        assert any(i.get("renamed_from") == "牛奶海" for i in out)
        assert not rejected

    def test_rename_invalid_new_name(self):
        out, applied, rejected = pc.apply_ops(
            _items(), [{"op": "rename_poi", "name": "牛奶海", "new_name": ""}])
        assert any(i["name"] == "牛奶海" for i in out)
        assert rejected

    def test_unknown_op_rejected(self):
        out, applied, rejected = pc.apply_ops(
            _items(), [{"op": "delete_everything"}])
        assert len(out) == 4
        assert rejected

    def test_reset_restores_from_original(self):
        """reset 必须恢复到筛选前的快照，而不是当前（已改过的）列表。"""
        original = _items()
        cur, _, _ = pc.apply_ops(original, [{"op": "drop_poi", "name": "牛奶海"}])
        assert len(cur) == 3
        out, applied, rejected = pc.apply_ops(cur, [{"op": "reset"}], original)
        assert len(out) == len(original), "reset 应恢复原始 4 个"

    def test_reset_without_original_falls_back(self):
        cur = _items()[:3]
        out, applied, _ = pc.apply_ops(cur, [{"op": "reset"}])
        assert len(out) == 3

    def test_ops_applied_in_order(self):
        ops = [{"op": "drop_poi", "name": "牛奶海"},
               {"op": "keep_kinds", "kinds": ["垭口"]}]
        out, applied, rejected = pc.apply_ops(_items(), ops)
        assert len(out) == 2
        assert len(applied) == 2

    def test_does_not_mutate_caller_data(self):
        original = _items()
        snapshot = json.dumps(original, ensure_ascii=False, sort_keys=True)
        pc.apply_ops(original, [{"op": "rename_poi", "name": "牛奶海",
                                 "new_name": "X"}])
        assert json.dumps(original, ensure_ascii=False, sort_keys=True) == snapshot, \
            "rename 不能改到调用方的数据"

    def test_drop_keeps_original_intact(self):
        original = _items()
        out, _, _ = pc.apply_ops(original, [{"op": "drop_poi", "name": "牛奶海"}])
        assert len(out) == 3
        assert len(original) == 4


class TestExtractJson:
    def test_plain(self):
        assert pc._extract_json('{"reply":"ok","ops":[]}') == {"reply": "ok", "ops": []}

    def test_fenced(self):
        fence = chr(96) * 3
        text = "好的\n" + fence + 'json\n{"reply":"a","ops":[]}\n' + fence
        assert pc._extract_json(text) == {"reply": "a", "ops": []}

    def test_prefixed_and_suffixed(self):
        text = '说明：{"reply":"x","ops":[]} 以上。'
        assert pc._extract_json(text) == {"reply": "x", "ops": []}

    def test_garbage(self):
        assert pc._extract_json("我不知道") is None
        assert pc._extract_json("") is None


class TestPrompt:
    def test_prompt_has_state_and_history(self):
        summary = {"tracks": [{"name": "洛亚大转"}], "distance_m": 49460.0,
                   "waypoint_count": 30}
        history = [{"role": "user", "content": "去掉湖泊"},
                   {"role": "assistant", "content": "已去掉 6 个湖泊"}]
        prompt = pc.build_prompt(summary, _items(), history, "再把牛场也去掉")
        assert "洛亚大转" in prompt
        assert "49.46 km" in prompt
        assert "黑湖垭口" in prompt
        assert "去掉湖泊" in prompt
        assert "再把牛场也去掉" in prompt
        assert "keep_kinds" in prompt
        assert "drop_poi" in prompt

    def test_prompt_handles_empty_pois(self):
        prompt = pc.build_prompt({}, [], [], "看看")
        assert "（无）" in prompt


class TestRunTurn:
    class _S:
        ai_api_key = "k"

    def test_no_key_raises(self, monkeypatch):
        from app import ai_naming
        monkeypatch.setattr(ai_naming, "is_configured", lambda s: False)
        with pytest.raises(pc.ChatError, match="未配置"):
            pc.run_turn({}, _items(), [], "去掉湖泊", self._S())

    def test_applies_ops_from_model(self, monkeypatch):
        from app import ai_naming
        monkeypatch.setattr(ai_naming, "is_configured", lambda s: True)
        monkeypatch.setattr(ai_naming, "chat", lambda p, s, sys="": json.dumps(
            {"reply": "已去掉湖泊", "ops": [{"op": "keep_kinds", "kinds": ["垭口", "营地"]}]}))
        r = pc.run_turn({}, _items(), [], "只留垭口和营地", self._S())
        assert len(r["items"]) == 3
        assert r["reply"] == "已去掉湖泊"
        assert r["applied"]

    def test_model_returns_garbage(self, monkeypatch):
        from app import ai_naming
        monkeypatch.setattr(ai_naming, "is_configured", lambda s: True)
        monkeypatch.setattr(ai_naming, "chat", lambda p, s, sys="": "我不明白")
        r = pc.run_turn({}, _items(), [], "??", self._S())
        assert len(r["items"]) == 4, "解析失败时不得改动数据"
        assert r["applied"] == []

    def test_model_gives_bad_op(self, monkeypatch):
        from app import ai_naming
        monkeypatch.setattr(ai_naming, "is_configured", lambda s: True)
        monkeypatch.setattr(ai_naming, "chat", lambda p, s, sys="": json.dumps(
            {"reply": "x", "ops": [{"op": "drop_poi", "name": "编造的地名"}]}))
        r = pc.run_turn({}, _items(), [], "删掉编造的地名", self._S())
        assert len(r["items"]) == 4
        assert r["rejected"]
