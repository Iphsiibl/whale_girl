# -*- coding: utf-8 -*-
"""「用户明确要语音」的判定规则。

现场（2026-11-26）：主人说「你用语音唱歌」「你发语音」，鲸鲸有时候只回文字。
根因是 REQUEST 只认「用语音(回|说|讲)」三种动词，其它说法（唱/念/报…）
匹配不上，只能掉进概率骰子（默认 25%），于是大部分时候发的是文字。

跑法：python -B tests/test_voice_request.py
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'bridge'))

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


if __name__ == '__main__':
    unittest.main()
