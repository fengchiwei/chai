# 理論基礎與文獻對照（THEORETICAL_FOUNDATIONS）

> 《少年仔、安啦會客室》（Anla Youth Room）風險分流引擎的理論依據說明
> 對應總計畫書〈參、跨領域風險分級標準〉；文件版本：2026-10-22（隨 `v1.3-A.1` 之後的整合版撰寫）

---

## 0. 閱讀前須知

1. **本文件說明「設計靈感的來源」，不是「臨床驗證的證明」。** 下列十項理論提供了風險分流規則的概念框架；系統中的所有門檻（例如「連續 3 輪」「≥2 個關注維度」「01:00–05:00」）都是**工程啟發式（engineering heuristics）**，由開發團隊參考文獻精神後自行設定，**沒有任何一項門檻值是直接取自文獻**，也未經臨床樣本校準。
2. **理論代號**（`PSY-01` … `HFE-06`）與程式碼一致。目前 `engine/triage.py` 已在回傳 JSON 的 `theoretical_basis` 欄位輸出這些代號，`engine/rules.py` 亦有對應註解。程式碼由多人同時開發，「系統對應」小節描述的是**設計意圖**；實際行為以程式碼與測試為準，兩者不一致時應以修正程式或修正本文件其一處理，不可默默放任。
3. **文獻查核原則**：所有引用皆於 2026-10-22 以網路檢索（期刊頁面、PubMed/PMC、Crossref 後設資料、ACL Anthology、大學典藏庫）逐筆核對作者、年份、篇名、刊名、卷期頁與 DOI。無法確認的細節一律省略或標示「待核對」。本文對研究結果的描述僅限於摘要層級可確認的內容。
4. 每節末尾的「⚠ 文獻與設計的落差」是**刻意保留的批判性註記**，供輔導老師、心理師與評審檢視。

---

## 1. 一頁總覽表

| 代號 | 理論 | 關鍵文獻 | 主要系統元件 |
| :--- | :--- | :--- | :--- |
| **PSY-01** | 哥倫比亞自殺嚴重程度量表（C-SSRS）：被動／主動意念、方法／意圖／計畫、準備行為 | Posner et al. (2011) | `engine/rules.py` 紅／橙規則；`engine/triage.py` |
| **PSY-02** | 人際自殺理論（IPTS）：知覺累贅感 PB × 受挫歸屬感 TB | Joiner (2005); Van Orden et al. (2010); Ma et al. (2016); Chu et al. (2017) | `engine/dialogue_policy.py` → `observe_safety` |
| **PSY-03** | 動機—意志整合模型（IMV）：挫敗、困頓（entrapment）、意志調節因子 | O'Connor (2011); O'Connor & Kirtley (2018); Siddaway et al. (2015) | `observe_safety`（困頓 × PB/TB）；`rules.py`（工具／方法） |
| **PSY-04** | 非自殺性自傷（NSSI）四功能模型 + DSM-5 時間框架 | Nock & Prinstein (2004); American Psychiatric Association (2013) | `engine/wellbeing_signals.py` 六大證據維度 |
| **LIN-01** | 言語行為理論 + 否定範疇偵測 | Austin (1962); Searle (1969, 1976); Chapman et al. (2001); Lapponi et al. (2012); Fancellu et al. (2016); Burnap et al. (2017) | `rules.py` 誇飾語旗標；`triage.py` 的 `pending_disambiguation` |
| **SIG-02** | 訊號偵測論 + 貝氏信念更新 + 非對稱損失 | Green & Swets (1966); Swets et al. (2000); Pauker & Kassirer (1980); Franklin et al. (2017); Belsher et al. (2019) | `triage.py`（以 wellbeing 維度作先驗，模糊句向上消歧） |
| **ENG-03** | 瑞士起司模型（多層獨立防禦）+ Fail-safe | Reason (1990, 2000); Perneger (2005) | 規則 → 身心先驗 → LLM 語義提示 → 伺服器高水位棘輪；本地安全模板 |
| **DYN-04** | 臨界慢化（CSD）+ 數位表型 | Scheffer et al. (2009); van de Leemput et al. (2014); Wichers et al. (2016); Helmich et al. (2024); Onnela & Rauch (2016); Kleiman et al. (2017); Tubbs et al. (2020); Rudd et al. (2006) | 對話狀態追蹤：負向情緒連續輪數、深夜時段、驟然道別 |
| **SOC-05** | 生態系統理論 + 自殺傳染／群聚 | Bronfenbrenner (1979); Gould et al. (2003); Hawton et al. (2020) | 第三人稱危機分流；`secondary_trauma_risk` |
| **HFE-06** | 警報疲勞 + 可解釋臨床決策支援 | Cash (2009); Ancker et al. (2017); Amann et al. (2020); Ghassemi et al. (2021) | `/explain` 儀表板、`engine/explain.py` |

跨理論背景文獻（AI 與自殺防治）：Bernert et al. (2020)；McBain et al. (2025)。

---

## 2. 臨床心理學四大支柱

### PSY-01　C-SSRS 哥倫比亞自殺嚴重程度量表

**參考文獻（APA 7）**

- Posner, K., Brown, G. K., Stanley, B., Brent, D. A., Yershova, K. V., Oquendo, M. A., Currier, G. W., Melvin, G. A., Greenhill, L., Shen, S., & Mann, J. J. (2011). The Columbia–Suicide Severity Rating Scale: Initial validity and internal consistency findings from three multisite studies with adolescents and adults. *American Journal of Psychiatry, 168*(12), 1266–1277. https://doi.org/10.1176/appi.ajp.2011.10111704

**核心概念**

C-SSRS 以「嚴重度階梯」描述自殺意念與行為，而不是單純的有／無二分。意念由輕到重依序為：希望死去（含「希望睡著不要醒來」這類被動死意）、非特定的主動自殺念頭、有想到方法但無意圖、有意圖但無具體計畫、有具體計畫與意圖。行為面則另外評估實際企圖、中斷／放棄的企圖，以及「準備行為」（如蒐集工具、寫遺書、交代身後事）。Posner 等人（2011）在三個含青少年與成人的多場域研究中，檢驗了量表的效度與意念強度分量表的內部一致性。這個階梯結構提醒我們：「說到死」本身並不等於同一級風險，關鍵在於是否出現方法、意圖、計畫與準備。

**系統對應**

- `engine/rules.py` 的紅／橙規則仿照此階梯分層：
  - **被動死意**（「睡著不要醒來」「消失就好了」）→ `orange`，並啟動一次溫和、非評判的探詢（例如確認現在是否安全、是否有想過傷害自己）。
  - **方法、計畫、準備行為**（遺書、把心愛物品送走、頂樓、提及工具）→ 直接 `red`，進入危機流程與真人轉介。
- `triage.py` 在紅燈或自傷相關橙燈時於 `theoretical_basis` 標註 `PSY-01`。

**⚠ 文獻與設計的落差**

- 依 Columbia 官方網站提供的篩檢版分流範例，第 1 題（被動死意）屬於**最低嚴重度層級**，通常對應「行為健康轉介」而非緊急處置。本系統把被動死意設為 `orange`，**比 C-SSRS 常見分流更保守**；這是針對「無人面對面、無法追問」的聊天情境所做的刻意選擇，不是 C-SSRS 的建議。
- 本系統**沒有**施測 C-SSRS，也未使用其題本；僅借用其嚴重度概念來組織關鍵詞規則。關鍵詞比對不是結構化訪談，不能宣稱具有 C-SSRS 的效度。

---

### PSY-02　人際自殺理論（Interpersonal Theory of Suicide, IPTS）

**參考文獻（APA 7）**

- Joiner, T. E. (2005). *Why people die by suicide*. Harvard University Press.
- Van Orden, K. A., Witte, T. K., Cukrowicz, K. C., Braithwaite, S. R., Selby, E. A., & Joiner, T. E., Jr. (2010). The interpersonal theory of suicide. *Psychological Review, 117*(2), 575–600. https://doi.org/10.1037/a0018697
- Ma, J., Batterham, P. J., Calear, A. L., & Han, J. (2016). A systematic review of the predictions of the Interpersonal–Psychological Theory of Suicidal Behavior. *Clinical Psychology Review, 46*, 34–45. https://doi.org/10.1016/j.cpr.2016.04.008
- Chu, C., Buchman-Schmitt, J. M., Stanley, I. H., Hom, M. A., Tucker, R. P., Hagan, C. R., Rogers, M. L., Podlogar, M. C., Chiurliza, B., Ringer, F. B., Michaels, M. S., Patros, C. H. G., & Joiner, T. E. (2017). The interpersonal theory of suicide: A systematic review and meta-analysis of a decade of cross-national research. *Psychological Bulletin, 143*(12), 1313–1345. https://doi.org/10.1037/bul0000123

**核心概念**

IPTS 把「想死的念頭」與「做得出來的能力」分開處理。Van Orden 等人（2010）的假設依序為：(1) **受挫歸屬感（TB）**與**知覺累贅感（PB）**各自即足以產生被動自殺意念；(2) 兩者同時存在、且當事人覺得這種狀態穩定不會改變（對兩者感到無望）時，產生主動的自殺渴望；(3) 渴望轉為意圖需要對死亡的恐懼降低；(4) 致命或近致命企圖最可能發生在上述條件再加上「習得的自殺能力」（對死亡無懼、疼痛耐受度提高）之時。系統性回顧（Ma et al., 2016）發現支持證據混合，其中 **PB 與自殺意念的關聯是被檢驗最多、支持最一致的一條**；統合分析（Chu et al., 2017）則顯示 TB × PB 交互作用與自殺意念顯著相關，但效果量不大。

**系統對應**

- `engine/dialogue_policy.py` 的 `observe_safety` 在對話層級累積 PB／TB 證據：
  - **PB 語句**（「我是家裡的累贅」「沒有我他們比較輕鬆」）或 **TB 語句**（「沒人要我」「在班上格格不入」「像透明人」）**單獨出現** → `yellow`，並標記 `stress_relationships`。
  - **同一場對話中兩者都出現** → `orange`，**即使全文沒有「死」字**。
- 這個「跨句累積」的設計，是為了接住那些從不使用危險關鍵字、但描述的處境已符合 IPTS 高風險構型的學生。

**⚠ 文獻與設計的落差**

- 依 IPTS，PB 與 TB 「同時存在」只有在**再加上對兩者的無望感**時，才被假設會產生主動自殺渴望。本系統在 PB＋TB 共現時即升 `orange`，**未要求無望感證據**，比理論更保守（寧可多一次真人確認）。
- 實證上 **PB 的支持度高於 TB**（Ma et al., 2016），但本系統把 PB 與 TB 單獨出現時給予相同權重（皆 `yellow`）。若日後要調整權重，應由輔導專業人員審視，而非僅依本文件推論。
- IPTS 的主要測量工具是問卷（如 Interpersonal Needs Questionnaire），本系統用的是中文口語關鍵詞，兩者並不等價。

---

### PSY-03　動機—意志整合模型（Integrated Motivational–Volitional Model, IMV）

**參考文獻（APA 7）**

- O'Connor, R. C. (2011). The integrated motivational-volitional model of suicidal behavior. *Crisis, 32*(6), 295–298. https://doi.org/10.1027/0227-5910/a000120
- O'Connor, R. C., & Kirtley, O. J. (2018). The integrated motivational–volitional model of suicidal behaviour. *Philosophical Transactions of the Royal Society B: Biological Sciences, 373*(1754), Article 20170268. https://doi.org/10.1098/rstb.2017.0268
- Siddaway, A. P., Taylor, P. J., Wood, A. M., & Schulz, J. (2015). A meta-analysis of perceptions of defeat and entrapment in depression, anxiety problems, posttraumatic stress disorder, and suicidality. *Journal of Affective Disorders, 184*, 149–159. https://doi.org/10.1016/j.jad.2015.05.046

**核心概念**

IMV 模型把自殺行為分為三階段：前動機期（背景與觸發事件）、動機期（意念如何形成）、意志期（意念如何轉為行動）。在動機期，**挫敗感（defeat）**與**困頓感／無路可逃（entrapment）**是自殺意念形成的核心驅動，並受「威脅自我調節因子」與「動機調節因子」（如歸屬感、累贅感、未來思維）影響。從意念走向行為，則取決於一組**意志調節因子（volitional moderators）**：取得致命工具的管道、接觸他人自殺行為、自殺能力、計畫、衝動性、心像以及過去自殺行為史（O'Connor & Kirtley, 2018）。統合分析顯示挫敗與困頓和多種精神病理及自殺性之間有強而一致的關聯（約 r = .60），但納入的研究多為橫斷設計，無法確立因果方向（Siddaway et al., 2015）。

**系統對應**

- **困頓語句**（「逃不出去」「完全沒有出路」「怎麼掙扎都沒用」）單獨出現 → 列入觀察（`yellow`）並觸發軟性確認。
- **困頓 + PB 或 TB** 於同一對話出現 → `orange`（IMV 的「動機調節因子」概念：歸屬與累贅會放大困頓走向意念的路徑）。
- **困頓 + 意志因子**（提及工具／藥物／高處、模仿同儕、過去自傷）→ `red`。這部分與 PSY-01 的「方法／準備」規則共用 `rules.py` 的紅燈判定。

**⚠ 文獻與設計的落差**

- IMV 是解釋模型，並未提供「哪些字詞組合等於哪個風險等級」的對照；本系統的組合規則是工程設計。
- 意志調節因子在 IMV 中是「調節」意念到行為的轉換，而非獨立的風險指標；本系統把「提及工具」直接視為紅燈，是出於安全考量的保守化約。

---

### PSY-04　NSSI 非自殺性自傷功能模型 + DSM-5 時間框架

**參考文獻（APA 7）**

- Nock, M. K., & Prinstein, M. J. (2004). A functional approach to the assessment of self-mutilative behavior. *Journal of Consulting and Clinical Psychology, 72*(5), 885–890. https://doi.org/10.1037/0022-006X.72.5.885
- American Psychiatric Association. (2013). *Diagnostic and statistical manual of mental disorders* (5th ed.). https://doi.org/10.1176/appi.books.9780890425596

**核心概念**

Nock 與 Prinstein（2004）以青少年精神科住院病人樣本檢驗自傷行為的功能，提出以「自動 vs. 社會」×「正增強 vs. 負增強」交叉而成的四功能模型：例如自傷可能用來緩解難以承受的情緒或麻木（自動負增強），也可能用來引起他人回應或逃避人際要求（社會增強）。這個模型的重點是「理解自傷為何持續」，以利評估與介入，而非用來預測死亡風險。DSM-5 將「非自殺性自傷」列於第三篇「需要進一步研究的狀況」（Conditions for Further Study），其提議準則的頻率條件是**過去一年中有 5 天以上**出現自傷；而「**持續至少兩週**」是**重鬱發作（major depressive episode）**準則 A 的時間要件，兩者不可混用。

**系統對應**

- `engine/wellbeing_signals.py` 以六個**證據綁定（evidence-bound）**的維度記錄學生自述的線索：`duration`、`sleep`、`daily_function`、`stress_relationships`、`safety`、`support_system`。每一筆紀錄都附上原話片段與輪次，作為可追溯證據。
- 當學生自述困擾已持續約兩週以上時，`duration` 維度記為 `time_mentioned`，僅作為「需要關注持續性」的提示。
- **從不自動評分、從不做診斷**：這六個維度不加總成分數、不輸出疾病名稱，只提供給後續的 SIG-02 先驗判斷與輔導人員參考。
- 自傷相關字詞（割、劃、刀、自殘、流血等）觸發的橙燈，`triage.py` 會在 `theoretical_basis` 標註 `PSY-04`，以提醒輔導者從「功能」角度理解（是在調節情緒？還是在求助？），而非僅視為自殺前兆。

**⚠ 文獻與設計的落差（重要）**

- **總計畫書把「DSM-5 持續兩週以上」與 NSSI 放在一起，這是錯置。** DSM-5 提議的 NSSI 準則是「過去一年 ≥5 天」，「≥2 週」屬於重鬱發作準則。本系統的「兩週」提示只能被理解為**一般性的持續性關注**（借用憂鬱症診斷的時間概念），**不可**在簡報或程式註解中寫成「DSM-5 的 NSSI 兩週準則」。建議後續修正程式註解與總計畫書的相關文字。
- 四功能模型與六大 wellbeing 維度之間**沒有一對一對應**；六大維度其實更接近一般心理健康篩檢的面向（睡眠、功能、支持系統），以 PSY-04 為其理論標籤屬於寬鬆借用。

---

## 3. 六大跨領域理論

### LIN-01　言語行為理論 + 否定範疇偵測

**參考文獻（APA 7）**

- Austin, J. L. (1962). *How to do things with words*. Clarendon Press.
- Searle, J. R. (1969). *Speech acts: An essay in the philosophy of language*. Cambridge University Press.
- Searle, J. R. (1976). A classification of illocutionary acts. *Language in Society, 5*(1), 1–23. https://doi.org/10.1017/S0047404500006837
- Chapman, W. W., Bridewell, W., Hanbury, P., Cooper, G. F., & Buchanan, B. G. (2001). A simple algorithm for identifying negated findings and diseases in discharge summaries. *Journal of Biomedical Informatics, 34*(5), 301–310. https://doi.org/10.1006/jbin.2001.1029
- Lapponi, E., Velldal, E., Øvrelid, L., & Read, J. (2012). UiO 2: Sequence-labeling negation using dependency features. In *\*SEM 2012: The First Joint Conference on Lexical and Computational Semantics* (pp. 319–327). Association for Computational Linguistics. https://aclanthology.org/S12-1042/
- Fancellu, F., Lopez, A., & Webber, B. (2016). Neural networks for negation scope detection. In *Proceedings of the 54th Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)* (pp. 495–504). Association for Computational Linguistics. https://doi.org/10.18653/v1/P16-1047
- Burnap, P., Colombo, G., Amery, R., Hodorog, A., & Scourfield, J. (2017). Multi-class machine classification of suicide-related communication on Twitter. *Online Social Networks and Media, 2*, 32–44. https://doi.org/10.1016/j.osnem.2017.08.001

**核心概念**

Austin（1962）指出說話本身就是在「做事」，同一句話的字面意義與其言外之力（illocutionary force）可以不同。Searle（1976）進一步把言外行為分為五類，其中**表達類（expressives）**是表達說話者的心理狀態（如抱怨、感嘆），**承諾類（commissives）**則是讓說話者承諾未來的行動。「熱到想死」「數學難到想死」在語用上多屬誇飾的表達類，與「我今晚就要去死」這類近似承諾類的宣告不同。在計算語言學中，「否定範疇偵測」處理的是否定詞究竟作用到哪些字詞：NegEx（Chapman et al., 2001）以規則與範圍終止詞限制否定的作用範圍，後續研究則使用依存句法特徵（Lapponi et al., 2012）或神經網路（Fancellu et al., 2016）判定範疇。社群媒體自殺語言分類研究也明確把「輕率／戲謔地提及自殺」（flippant reference）列為需與真正令人擔憂內容區分的獨立類別（Burnap et al., 2017）。

**系統對應**

- **誇飾遮蔽（hyperbole masking）**：`rules.py` 以 `[熱|累|餓|煩|…]到想死`、「累到快往生」等型式辨識表達類誇飾，產生 `hyperbole_flags`。
  - 有誇飾旗標且無其他自傷訊號時，`triage.py` 設定 `pending_disambiguation = True`，風險為 `yellow`，並送出一次**軟性確認句**（例如「聽起來真的很累，想確認一下，你說的『想死』是很煩的意思，還是有時候真的會有不想活的念頭？」）。
  - **誇飾語絕不被靜默丟棄**：既不直接鎖紅，也不當作沒說過。
- **子句邊界否定**：否定詞（沒有、不是、不會）的作用範圍限制在同一子句（以 `，。！？；` 為界），避免「我沒有說謊，朋友說他想死」這類句子中，前句的否定詞把後句的警訊遮蔽掉。
- **運動受詞排除**：「打羽球」「殺球」「殺時間」中的「打／殺」帶運動或遊戲受詞時，不判定為暴力意圖。

**⚠ 文獻與設計的落差**

- Searle 的五分類（含 expressive／commissive）出自 **1976 年**的論文，而非 1969 年的專書；本文已分列引用。
- 文獻中的否定範疇是**句法**現象，NegEx 也是以否定片語與終止詞決定範圍；本系統以**標點切分子句**是更粗略的近似，對無標點的長句或口語化輸入可能失準。上列 NLP 文獻皆以英文語料為主，**未驗證於繁體中文青少年口語**。
- 「誇飾 → 降為 yellow」是本系統風險最高的設計決策之一：對某些學生來說，「熱到想死」可能是用玩笑包裝的真實念頭。因此本降級規則**必須經學校輔導老師／心理師審閱**，且軟性確認句不得省略（見第 5 節）。

---

### SIG-02　訊號偵測論 + 貝氏信念更新 + 非對稱損失

**參考文獻（APA 7）**

- Green, D. M., & Swets, J. A. (1966). *Signal detection theory and psychophysics*. Wiley.
- Swets, J. A., Dawes, R. M., & Monahan, J. (2000). Psychological science can improve diagnostic decisions. *Psychological Science in the Public Interest, 1*(1), 1–26. https://doi.org/10.1111/1529-1006.001
- Pauker, S. G., & Kassirer, J. P. (1980). The threshold approach to clinical decision making. *New England Journal of Medicine, 302*(20), 1109–1117. https://doi.org/10.1056/NEJM198005153022003
- Franklin, J. C., Ribeiro, J. D., Fox, K. R., Bentley, K. H., Kleiman, E. M., Huang, X., Musacchio, K. M., Jaroszewski, A. C., Chang, B. P., & Nock, M. K. (2017). Risk factors for suicidal thoughts and behaviors: A meta-analysis of 50 years of research. *Psychological Bulletin, 143*(2), 187–232. https://doi.org/10.1037/bul0000084
- Belsher, B. E., Smolenski, D. J., Pruitt, L. D., Bush, N. E., Beech, E. H., Workman, D. E., Morgan, R. L., Evatt, D. P., Tucker, J., & Skopp, N. A. (2019). Prediction models for suicide attempts and deaths: A systematic review and simulation. *JAMA Psychiatry, 76*(6), 642–651. https://doi.org/10.1001/jamapsychiatry.2019.0174

**核心概念**

訊號偵測論把每一次判斷拆成兩個獨立成分：**區辨力**（能否分辨訊號與雜訊）與**判準**（傾向回答「有」還是「沒有」）。判準應依「漏報」與「誤報」的相對代價來設定：當漏報的代價遠高於誤報時，理性的決策者應把判準放低（Swets et al., 2000）。Pauker 與 Kassirer（1980）的「門檻法」把同樣的邏輯帶入臨床：依疾病機率是否跨越「檢查門檻」或「治療門檻」，決定要觀察、進一步檢查還是直接處置。貝氏更新則說明先驗資訊（學生先前透露的睡眠、功能與壓力狀況）如何改變對一句模糊話語的解讀。然而，大型統合分析也提醒：傳統自殺危險因子的預測力只比隨機稍好（Franklin et al., 2017），而在低盛行率下，即便整體分類表現不錯的模型，其陽性預測值仍很低（Belsher et al., 2019）。

**系統對應**

- **先驗**：`wellbeing_signals` 中已出現「關注狀態」的維度數，作為該學生在此對話中的粗略先驗。
- **更新**：遇到誇飾或模糊句（「好想消失」「活著好累」）時：
  - 若先驗維度大多為 `unknown` → `yellow` + `pending_disambiguation` + 軟性確認。
  - 若已有 **≥2 個關注維度**（例如失眠 + 功能受損 + 家庭壓力）→ 視為後驗跨越門檻，升為 `orange`。
- **非對稱損失**：漏接一位真正有危險的學生，代價遠高於多問一次「你還好嗎」。因此**所有模糊性一律向上消歧到「真人確認」，絕不向下消歧為「安全」**。

**⚠ 文獻與設計的落差（重要）**

- 本系統**並未計算任何機率**。「先驗」「後驗」「跨越門檻」是**比喻性用語**，實作上是維度計數與固定規則。不可對外宣稱系統執行了貝氏推論或輸出校準過的風險機率。
- Franklin 等人（2017）的結論是：單一或少數危險因子的預測力接近隨機。因此「≥2 個維度」作為升級門檻**沒有實證預測效度**，只是保守的工程選擇。
- SIG-02「一律向上」與 HFE-06「防止警報疲勞」之間存在**本質張力**：在低盛行率下向上消歧必然帶來大量誤報（Belsher et al., 2019 所描述的低陽性預測值問題）。本系統以「`pending_disambiguation` 獨立顯示、不與確認危機混列」來緩解，但無法消除此張力。

---

### ENG-03　瑞士起司模型 + Fail-safe 降級

**參考文獻（APA 7）**

- Reason, J. (1990). *Human error*. Cambridge University Press. https://doi.org/10.1017/CBO9781139062367
- Reason, J. (2000). Human error: Models and management. *BMJ, 320*(7237), 768–770. https://doi.org/10.1136/bmj.320.7237.768
- Perneger, T. V. (2005). The Swiss cheese model of safety incidents: Are there holes in the metaphor? *BMC Health Services Research, 5*, Article 71. https://doi.org/10.1186/1472-6963-5-71

**核心概念**

Reason（2000）區分了看待錯誤的「個人取向」與「系統取向」，並以瑞士起司比喻說明：複雜系統中有多層防禦，每一層都有無法避免的漏洞（包括第一線的主動失誤與系統中潛伏的條件），只有當各層的漏洞恰好對齊時，危害才會穿透所有防線造成傷害。因此安全設計的重點不是追求某一層完美，而是讓多層防禦**彼此獨立**、漏洞不易同時對齊。Perneger（2005）調查醫療品質與安全專業人員後發現，雖然多數人自認熟悉此模型，但對其各元件（起司片、洞、箭頭）的詮釋差異頗大，提醒使用者需要明確定義各層代表什麼。

**系統對應**

四層防禦，各層只能**提高**風險，不能降低前一層的判定：

| 層 | 元件 | 角色 |
| :--- | :--- | :--- |
| Layer 1 | `engine/rules.py` 確定性規則 | 可重現、可測試的紅／橙／黃關鍵型式 |
| Layer 2 | `engine/wellbeing_signals.py` 身心先驗 | 跨輪累積的證據維度（SIG-02） |
| Layer 3 | `engine/dialogue_ai.py` LLM 語義提示 | 補捉規則漏掉的語意；**只能升級，不能降級** |
| Layer 4 | 伺服器端高水位棘輪（`max_risk_level`） | 同一對話內風險等級**永不下降** |

- **Fail-safe**：模型逾時、API 錯誤或回應格式異常時，由本地安全模板接手回覆，不回傳 HTTP 500，也不因模型失效而降低風險等級。

**⚠ 文獻與設計的落差**

- 瑞士起司模型的效力建立在**各層獨立**；本系統四層皆讀取**同一段使用者文字**，若學生的表達方式同時避開規則與 LLM 的辨識（例如隱喻、外語、表情符號），各層的漏洞可能**同時對齊**。這是共因失效（common-cause failure）風險，而非真正獨立。
- 「只升不降」的棘輪可防止漏報，但也代表**誤報一旦發生就會留存整場對話**；這是有意的取捨，需由後台人工複核來修正。

---

### DYN-04　臨界慢化（Critical Slowing Down）+ 數位表型

**參考文獻（APA 7）**

- Scheffer, M., Bascompte, J., Brock, W. A., Brovkin, V., Carpenter, S. R., Dakos, V., Held, H., van Nes, E. H., Rietkerk, M., & Sugihara, G. (2009). Early-warning signals for critical transitions. *Nature, 461*(7260), 53–59. https://doi.org/10.1038/nature08227
- van de Leemput, I. A., Wichers, M., Cramer, A. O. J., Borsboom, D., Tuerlinckx, F., Kuppens, P., van Nes, E. H., Viechtbauer, W., Giltay, E. J., Aggen, S. H., Derom, C., Jacobs, N., Kendler, K. S., van der Maas, H. L. J., Neale, M. C., Peeters, F., Thiery, E., Zachar, P., & Scheffer, M. (2014). Critical slowing down as early warning for the onset and termination of depression. *Proceedings of the National Academy of Sciences, 111*(1), 87–92. https://doi.org/10.1073/pnas.1312114110
- Wichers, M., Groot, P. C., Psychosystems, ESM Group, & EWS Group. (2016). Critical slowing down as a personalized early warning signal for depression. *Psychotherapy and Psychosomatics, 85*(2), 114–116. https://doi.org/10.1159/000441458
- Helmich, M. A., Schreuder, M. J., Bringmann, L. F., Riese, H., Snippe, E., & Smit, A. C. (2024). Slow down and be critical before using early warning signals in psychopathology. *Nature Reviews Psychology, 3*(11), 767–780. https://doi.org/10.1038/s44159-024-00369-y
- Onnela, J.-P., & Rauch, S. L. (2016). Harnessing smartphone-based digital phenotyping to enhance behavioral and mental health. *Neuropsychopharmacology, 41*(7), 1691–1696. https://doi.org/10.1038/npp.2016.7
- Kleiman, E. M., Turner, B. J., Fedor, S., Beale, E. E., Huffman, J. C., & Nock, M. K. (2017). Examination of real-time fluctuations in suicidal ideation and its risk factors: Results from two ecological momentary assessment studies. *Journal of Abnormal Psychology, 126*(6), 726–738. https://doi.org/10.1037/abn0000273
- Tubbs, A. S., Perlis, M. L., Basner, M., Chakravorty, S., Khader, W., Fernandez, F., & Grandner, M. A. (2020). Relationship of nocturnal wakefulness to suicide risk across months and methods of suicide. *The Journal of Clinical Psychiatry, 81*(2), Article 19m12964. https://doi.org/10.4088/JCP.19m12964
- Rudd, M. D., Berman, A. L., Joiner, T. E., Jr., Nock, M. K., Silverman, M. M., Mandrusiak, M., Van Orden, K., & Witte, T. (2006). Warning signs for suicide: Theory, research, and clinical applications. *Suicide and Life-Threatening Behavior, 36*(3), 255–262. https://doi.org/10.1521/suli.2006.36.3.255

**核心概念**

Scheffer 等人（2009）指出，許多複雜系統在接近「臨界轉換」（tipping point）時，從小擾動恢復的速度會變慢，在時間序列上表現為自相關與變異數上升，稱為臨界慢化。van de Leemput 等人（2014）以經驗取樣資料報告，憂鬱的發作與緩解前可觀察到情緒波動的自相關、變異與情緒間相關上升；Wichers 等人（2016）則在單一個案中嘗試以此作為個人化預警。不過，2024 年的觀點回顧結論相當保守：以情緒時間序列計算的臨界慢化指標，目前**很少有證據支持其在臨床心理學中作為預警使用**，臨床應用需要能前瞻、即時、針對個人預測「是否」與「何時」變化（Helmich et al., 2024）。數位表型（Onnela & Rauch, 2016）主張以個人數位裝置的資料即時、就地測量行為；生態瞬時評估研究亦顯示，自殺意念與其危險因子可在數小時內大幅波動（Kleiman et al., 2017）。另外，以美國死亡登錄資料結合時間使用調查的研究發現，**相對於當時清醒的人口比例**，夜間的自殺風險高於一天中其他時段（Tubbs et al., 2020）；Rudd 等人（2006）則區分了「警訊」（近期、可觀察的徵兆）與「危險因子」（長期背景特徵），並提出美國自殺學會工作小組的共識警訊清單。

**系統對應**

對話狀態中追蹤三項「軟性動態訊號」，任一符合即觸發一次溫和的關心確認（不單獨鎖紅）：

1. **負向情緒持續**：連續 ≥3 輪呈現無望、負向迴圈的內容。
2. **深夜時段**：訊息時間落在 01:00–05:00。
3. **驟然道別**：在數則長篇傾訴之後，突然只回「算了」「謝謝你」「再見」這類短句。

**⚠ 文獻與設計的落差（重要）**

- **本系統並未偵測臨界慢化。** CSD 指標需要長而密集的時間序列（例如數週的經驗取樣資料）來估計自相關與變異的趨勢；在單次對話的 3 輪內不可能估計這些統計量。「連續 3 輪負向」只是**受 CSD「慢慢陷入、難以回彈」概念啟發的啟發式規則**，對外說明時不可稱為「CSD 偵測」或「相變點預測」。
- 而且 Helmich 等人（2024）指出，即使資料充足，CSD 預警在心理病理上的實證支持也很有限。DYN-04 宜定位為「關心提示」，而非預測器。
- Tubbs 等人（2020）研究的是**自殺死亡發生的時間**，不是「深夜傳訊」；01:00–05:00 的時窗是工程選擇。深夜傳訊在青少年中也非常普遍，單獨使用會造成大量誤報，所以本系統只把它當作軟性訊號。
- 「驟然道別」並無直接的實證研究支持其在聊天機器人中的預測力，只是借用臨床警訊的精神。

---

### SOC-05　生態系統理論 + 自殺傳染／群聚

**參考文獻（APA 7）**

- Bronfenbrenner, U. (1979). *The ecology of human development: Experiments by nature and design*. Harvard University Press.
- Gould, M., Jamieson, P., & Romer, D. (2003). Media contagion and suicide among the young. *American Behavioral Scientist, 46*(9), 1269–1284. https://doi.org/10.1177/0002764202250670
- Hawton, K., Hill, N. T. M., Gould, M., John, A., Lascelles, K., & Robinson, J. (2020). Clustering of suicides in children and adolescents. *The Lancet Child & Adolescent Health, 4*(1), 58–67. https://doi.org/10.1016/S2352-4642(19)30335-9

**核心概念**

Bronfenbrenner（1979）主張發展必須放在層層嵌套的環境中理解：與個體直接互動的微系統（家庭、班級、朋友）、微系統之間的連結（中間系統，例如家長與學校的關係），以及更外層的制度與文化脈絡。對青少年而言，家庭與同儕這兩個微系統同時斷裂，意味著支持網絡的多重失效。自殺傳染（contagion）研究則探討青少年接觸自殺相關媒體報導後的模仿風險（Gould et al., 2003），兒童與青少年在時間與空間上聚集發生的自殺群聚現象也已有系統性回顧（Hawton et al., 2020）。這代表「目睹或得知朋友有危險」的學生本身也是需要被照顧的對象，而不只是傳話者。

**系統對應**

- **第三人稱危機**（「朋友說他想死」「我閨蜜吞了安眠藥」）→ 依急迫性列為 `orange` 或 `red`：
  - 提供具體的協助步驟（陪在朋友身邊、移除可取得的危險物品、立即告知可信任的大人或撥打 119／110、聯繫學校輔導室）。
  - 同時將使用者本人標記 `secondary_trauma_risk`，給予情緒減壓與支持，承認「接住朋友很辛苦，你不必一個人扛」。
- **「請幫我保密」的界線**：當朋友的生命有危險時，系統會溫和但明確地說明「保密」不適用，並鼓勵學生告訴大人；這是守門人訓練的基本原則，也是對學生本人的保護。
- **雙重微系統斷裂**：家庭與同儕支持同時受挫、且 `support_system` 為負向時，提高關注程度。
- 回覆內容遵循安全訊息原則：**不描述自殺方法細節**，以避免本系統自身成為傳染途徑。

**⚠ 文獻與設計的落差**

- Bronfenbrenner 的理論是發展心理學的描述框架，**不是風險評分模型**；「雙重斷裂 → 提高權重」是本系統的推論。
- 傳染研究多以媒體報導與族群層級資料為主，本系統把它延伸到「學生聽到朋友說想死」的個別情境，方向一致但屬延伸應用。

---

### HFE-06　警報疲勞 + 可解釋臨床決策支援

**參考文獻（APA 7）**

- Cash, J. J. (2009). Alert fatigue. *American Journal of Health-System Pharmacy, 66*(23), 2098–2101. https://doi.org/10.2146/ajhp090181
- Ancker, J. S., Edwards, A., Nosal, S., Hauser, D., Mauer, E., Kaushal, R., & the HITEC Investigators. (2017). Effects of workload, work complexity, and repeated alerts on alert fatigue in a clinical decision support system. *BMC Medical Informatics and Decision Making, 17*, Article 36. https://doi.org/10.1186/s12911-017-0430-8
- Amann, J., Blasimme, A., Vayena, E., Frey, D., Madai, V. I., & the Precise4Q consortium. (2020). Explainability for artificial intelligence in healthcare: A multidisciplinary perspective. *BMC Medical Informatics and Decision Making, 20*, Article 310. https://doi.org/10.1186/s12911-020-01332-6
- Ghassemi, M., Oakden-Rayner, L., & Beam, A. L. (2021). The false hope of current approaches to explainable artificial intelligence in health care. *The Lancet Digital Health, 3*(11), e745–e750. https://doi.org/10.1016/S2589-7500(21)00208-9

**核心概念**

警報疲勞指的是臨床人員在大量、重複、低價值的系統警示轟炸下，逐漸對警示麻木、習慣性略過，最終連真正重要的警示也一併忽略（Cash, 2009）。Ancker 等人（2017）則在實際的臨床決策支援系統中，檢驗了工作量、工作複雜度與重複警示對警報疲勞的影響。可解釋性被視為醫療 AI 的多面向議題，涉及技術、法律、醫療與病人觀點（Amann et al., 2020）；但也有學者警告，目前的事後解釋方法未必能可靠地說明個別決策，不應被當作信任的保證（Ghassemi et al., 2021）。對本系統而言，可解釋性的較穩健做法是**呈現可驗證的原始證據**，而非生成的解釋文字。

**系統對應**

- `/explain` 儀表板（`app.py` 的 `explain_dashboard`、`engine/explain.py`）：
  - **確認危機**（紅／橙）以**實線**卡片呈現；**待消歧語句**（`pending_disambiguation`，黃）以**虛線**呈現，視覺上明確分離，避免輔導老師被大量「熱到想死」淹沒。
  - 每張風險卡顯示：**原話螢光筆高亮**（逐字證據）、**觸發規則來源**、**理論代號**（`theoretical_basis`）。
- 設計目標是讓輔導老師在數秒內看懂「系統為什麼這樣判、證據是哪一句」，並能據此推翻系統判斷。

**⚠ 文獻與設計的落差**

- 警報疲勞的文獻主要來自醫院用藥警示等情境，**未在學校輔導情境驗證**；「虛線／實線分離能降低疲勞」是合理推論，尚無本系統的使用者研究數據。
- 依 Ghassemi 等人（2021）的提醒，本系統**不以 LLM 生成的理由作為解釋依據**；解釋以逐字證據與確定性規則來源為主。

---

## 4. 跨理論背景：AI 與自殺防治

- Bernert, R. A., Hilberg, A. M., Melia, R., Kim, J. P., Shah, N. H., & Abnousi, F. (2020). Artificial intelligence and suicide prevention: A systematic review of machine learning investigations. *International Journal of Environmental Research and Public Health, 17*(16), Article 5929. https://doi.org/10.3390/ijerph17165929
- McBain, R. K., Cantor, J. H., Zhang, L. A., Baker, O., Zhang, F., Burnett, A., Kofner, A., Breslau, J., Stein, B. D., Mehrotra, A., & Yu, H. (2025). Evaluation of alignment between large language models and expert clinicians in suicide risk assessment. *Psychiatric Services, 76*(11), 944–950. https://doi.org/10.1176/appi.ps.20250086

McBain 等人（2025）以 30 個由臨床專家分級的自殺相關問題反覆測試三個通用聊天機器人，發現它們對極低風險與極高風險問題的處理大致符合專家判斷，但對**中間風險**問題的回應不一致。這正是本系統不把風險判斷交給 LLM、而以確定性規則為底層（ENG-03 Layer 1）並限制 LLM「只能升級」的主要理由。

---

## 5. 限制與倫理聲明

1. **這是原型（prototype）。** 《少年仔、安啦會客室》是教育與研究用途的原型系統，不是醫療器材，不提供診斷，也不能取代學校輔導老師、心理師、精神科醫師或緊急救援服務。
2. **所有門檻都是啟發式。** 文中提到的「連續 3 輪」「≥2 個關注維度」「01:00–05:00」「PB＋TB 共現即升橙」等，皆為開發團隊依文獻精神自行設定的工程門檻，**沒有任何一項取自文獻、也未經臨床資料校準**。
3. **規則測試不是臨床驗證。** 專案中的單元測試與情境測試（`tests/`）只驗證「程式是否照設計規則運作」，不代表系統能正確辨識真實青少年的風險；本專案**未進行**任何以真實個案為對象的敏感度、特異度或陽性預測值研究。
4. **不宣稱召回率，不宣稱「零漏報」。** 本系統**不保證**能偵測到所有高風險訊息。任何「零漏報」「100% 偵測」之類的說法都不正確，不得用於簡報、比賽文件或宣傳。四層防禦（ENG-03）只能降低、無法消除漏報。
5. **誇飾降級需專業審閱。** LIN-01 將「熱到想死」等誇飾語降為 `yellow`（待消歧）是本系統最需謹慎的決策。此規則與其軟性確認話術**必須經學校輔導老師／心理師審閱同意**後才能用於真實學生；在審閱完成前，建議部署時改以 `orange` 處理或維持人工複核。
6. **文獻與設計的已知落差**已在各節「⚠」中逐一列出，特別是：PSY-04 的「兩週」不是 DSM-5 NSSI 準則；DYN-04 並未真正計算臨界慢化；SIG-02 並未計算機率。
7. **文化與語言限制。** 本文引用的實證研究多以英語系國家樣本為主；中文口語（尤其台灣青少年用語、網路流行語、注音文、台語詞彙）的語用與否定結構未經驗證。
8. **人在迴路中（human-in-the-loop）。** 系統的角色是「把需要關心的學生更早交到真人手上」，所有 `orange`／`red` 判定都應由受過訓練的成人複核與跟進。

---

## 6. 文獻查核紀錄

- 查核日期：2026-10-22。
- 查核方式：期刊官方頁面、PubMed/PMC、Crossref 後設資料 API、ACL Anthology、出版社與大學典藏庫、圖書館目錄。
- 已逐筆核對作者、年份、篇名、刊名／出版社、卷期頁與 DOI 的文獻：**42 筆**（本文第 2–4 節所列全部條目）。
- 標示「待核對」：**0 筆**。
- 補充說明：
  - Searle (1976) 頁碼依 Crossref 記錄為 1–23（另有一份二手書目記為 1–24，以 Crossref 為準）。
  - Joiner (2005) 依 2005 年 Harvard University Press 精裝版引用；平裝版為 2007 年。
  - Wichers et al. (2016) 部分典藏庫將其列為致編輯函（letter），屬單一個案報告。
  - 各研究的結果描述僅限摘要層級可確認的內容；未取得全文者，未引述其細部數據。
