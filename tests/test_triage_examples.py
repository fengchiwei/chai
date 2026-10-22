"""使用者提供情境的部分回歸案例；這些標籤是測試預期，非臨床判定。"""
import unittest
from engine.triage import perform_triage


class TriageExamples(unittest.TestCase):
    def test_user_supplied_orange_and_red_phrases(self):
        examples = [
            ("有時候真的覺得，如果我哪天突然消失在世界上，對大家都好。", "orange"),
            ("好希望晚上睡著之後就再也不要醒來了，活著真的很沒意思。", "orange"),
            ("最近常常在想，要是死了是不是就能解脫這些煩惱了。", "orange"),
            ("活在這個家簡直是地獄，我真想一死百了逃離這裡。", "orange"),
            ("心裡會突然冒出一個念頭：如果現在衝出去被撞死，一切就結束了。", "orange"),
            ("一直覺得去死一死算了吧，但我又沒有勇氣去實行。", "orange"),
            ("我把工具都準備好藏在書包裡了，等今晚家人都睡著，我就會行動，再見。", "red"),
            ("我計畫好明天放學後去一個沒人的地方結束這一切，只是想來這裡做最後的告別。", "red"),
            ("我現在一個人鎖在房間裡，東西都弄好了，倒數五分鐘我就要離開這個世界。", "red"),
            ("我決定今天晚上一次全部解決掉，我已經確認過這個數量一定夠。", "red"),
        ]
        for phrase, expected in examples:
            with self.subTest(phrase=phrase):
                self.assertEqual(perform_triage(phrase)["level"], expected)

    def test_negated_or_third_person_statement(self):
        self.assertEqual(perform_triage("我沒有想死，也不會傷害自己")["level"], "green")
        self.assertEqual(perform_triage("朋友說他要燒炭，我很擔心他")["level"], "green")


if __name__ == "__main__":
    unittest.main()
