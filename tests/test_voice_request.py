# -*- coding: utf-8 -*-
"""「用户明确要语音」的判定规则。

现场（2026-11-26）：主人说「你用语音唱歌」「你发语音」，鲸鲸有时候只回文字。
根因是 REQUEST 只认「用语音(回|说|讲)」三种动词，其它说法（唱/念/报…）
匹配不上，只能掉进概率骰子（默认 25%），于是大部分时候发的是文字。

跑法：python -B tests/test_voice_request.py
"""
import os
import sys
import json
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'bridge'))

import voice_reply  # noqa: E402
from voice_reply import NEGATIVE, REQUEST, requested  # noqa: E402


class VoiceRequest(unittest.TestCase):
    def test_common_explicit_requests(self):
        for text in ('你用语音唱歌', '用语音唱', '你发语音', '发个语音', '来条语音',
                     '你用语音说', '用语音念首诗', '语音来一条', '语音版发我',
                     '你用语音报个时间', '发条语音', '语音回复我', '用语音整一段'):
            self.assertTrue(REQUEST.search(text), '没认出「%s」' % text)

    def test_negative_still_blocks(self):
        for text in ('别用语音', '不要语音', '用文字回复', '语音怎么发', '关闭语音'):
            self.assertFalse(requested(text), '不该认成「%s」' % text)

    def test_plain_chat_is_not_a_request(self):
        for text in ('你好', '语音识别怎么用', '今天天气不错', '群名改成py交流群'):
            self.assertFalse(requested(text), '不该认成「%s」' % text)

    def test_quoted_lines_do_not_block(self):
        # 台词里带引号/「别」时，不该把整条判成「不是明确要求」。
        self.assertTrue(requested('你用语音说："唱首歌"'))

    def test_length_limit(self):
        self.assertFalse(requested('你用语音' + '啊' * 600))


class VoiceRetry(unittest.TestCase):
    """录音被前台变化打断时重试一次（微信那条没发出去，重试不算重复发送）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='whale-voice-')
        os.makedirs(os.path.join(self.tmp, 'data'))
        with open(os.path.join(self.tmp, 'data', 'voice-send.json'), 'w', encoding='utf-8') as f:
            json.dump({'Enabled': True, 'Probability': 15}, f)
        self.calls = []
        self.original = voice_reply._deliver_once

    def tearDown(self):
        voice_reply._deliver_once = self.original
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _stub(self, results):
        def fake(root, text, hwnd, prepare, log, allow_foreground=None, cancelled=None,
                 outcome=None, send_lock=None):
            self.calls.append(text)
            return results[min(len(self.calls) - 1, len(results) - 1)]
        voice_reply._deliver_once = fake

    def test_focus_lost_error_is_recognized(self):
        self.assertTrue(voice_reply.focus_lost_error('窗口或会话已变化，取消本次录音'))
        self.assertFalse(voice_reply.focus_lost_error('语音合成超时（85s）'))
        self.assertFalse(voice_reply.focus_lost_error(''))

    def test_retries_once_after_focus_loss(self):
        self._stub([(True, 'uncertain', '窗口或会话已变化，取消本次录音'),
                    (True, 'sent_unconfirmed', '')])
        outcome = {}
        ok = voice_reply.deliver(self.tmp, '在吗', 123, lambda: 'chat', lambda *a: None,
                                 outcome=outcome)
        self.assertEqual(len(self.calls), 2, '应该重试一次')
        self.assertTrue(ok)
        self.assertEqual(outcome.get('Status'), 'sent_unconfirmed')

    def test_other_failures_are_not_retried(self):
        self._stub([(True, 'uncertain', '语音录音发送超时')])
        voice_reply.deliver(self.tmp, '在吗', 123, lambda: 'chat', lambda *a: None)
        self.assertEqual(len(self.calls), 1, '只有前台变化才重试')

    def test_gives_up_after_second_failure(self):
        self._stub([(True, 'uncertain', '窗口或会话已变化，取消本次录音')])
        outcome = {}
        ok = voice_reply.deliver(self.tmp, '在吗', 123, lambda: 'chat', lambda *a: None,
                                 outcome=outcome)
        self.assertEqual(len(self.calls), 2, '最多重试一次')
        self.assertTrue(ok, '结果不确定时仍然算「可能已发送」，避免再补一条文字')
        self.assertEqual(outcome.get('Status'), 'uncertain')


if __name__ == '__main__':
    unittest.main()
