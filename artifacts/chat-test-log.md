# 會客室本地對話實測紀錄

時間帶：Asia/Taipei（UTC+08:00）。下列時間戳皆含時區。

## 測試環境

- 網址：http://127.0.0.1:5000/（只在這台 VM 本機，未碰 ngrok、未部署）
- 程式版本：main，commit fb03b072cab57fd89ed5fc7c529b7699872310ac（v2.9.5）
- 啟動方式：未帶任何模型金鑰。程序環境用 env -i 清除後只留 PATH、HOME、LANG、DATABASE_PATH=/tmp/anla-run/chat-test.db、HOST=127.0.0.1。沒有讀取或寫入金鑰、.env。
- 模型：沒有另外寫 mock 端點。未設定金鑰時，一般對話走程式既有的固定說明（engine/dialogue_ai.py 的 unavailable_reply，狀態 no_key／builtin）。危機句「我不想活了」走程式既有的本地安全文字（engine/dialogue_reply.py 的 safety_reply），不是雲端模型，也不是本次新增的 mock。
- 瀏覽器：Google Chrome 156.0.8078.47，headless，視窗 1280×1600。自動化只操作輸入、發送、資料說明勾選，以及開始新對話的確認框。危機面板沒有打開，所以沒有按「繼續對話」。沒有點任何 tel: 連結。
- 送出前必須先勾選資料使用說明。本次在畫面填暱稱「測試同學」、勾選已閱讀，按「先聊聊」。這會打到本機 /api/onboarding，不是外部 API。
- 05:33:04 有一次腳本在送出任何對話前就中斷（測試程式把 DOM 事件的 kind 欄位傳錯）。那次只有開啟首頁。下面的逐則紀錄是 05:33:16 重新跑完的那一次。伺服器 log 兩次載入都在。

## 開場白（頁面一載入就在畫面上，不是本次送出的回覆）

記錄時間：2026-10-31T05:33:17.804+08:00。狀態燈文字：尚未接上 AI。

氣泡 innerText 原文（含版面留下的空白；已去掉「朗讀這段話」按鈕）：

```

              哈囉少年仔！我是「安啦會客室」的 AI 陪伴夥伴。👋
              無論是段考讀不完、跟朋友有小摩擦、在學校覺得孤單，或是家裡的壓力，
              在這裡你可以放鬆把心事說出來，按下方麥克風 🎙️ 也可以直接用說的喔！
              我會先聽你說；如果現在有立即危險，請直接使用下方的電話求助。
              
                
              
            
```


## 輸入框與空白送出

- 2026-10-31T05:33:18.089+08:00 資料說明視窗還開著時，輸入框 displayed=True、enabled=True；發送鈕文字「發送 ✈️」、displayed=True、enabled=True。
- 2026-10-31T05:33:19.141+08:00 點輸入框失敗。錯誤原文：

```
ElementClickInterceptedException: Message: element click intercepted: Element <input type="text" id="userInput" maxlength="2000" aria-label="想說的話（2000 字以內）" placeholder="輸入文字或點擊左側 🎙️ 說說你的心情...（按 Enter 發送）" onkeypress="if(event.key === 'Enter') sendMessage()"> is not clickable at point (436, 859). Other element would receive the click: <label style="display:block;margin-bottom:.8rem;font-size:.82rem;line-height:1.5;">...</label>
  (Session info: chrome=156.0.8078.47); For documentation on this error, please visit: https://www.selenium.dev/documentation/webdriver/troubleshooting/errors#elementclickinterceptedexception
Stacktrace:
#0 0x55f2802ee0aa <unknown>
#1 0x55f27fc21875 <unknown>
#2 0x55f27fc68d61 <unknown>
#3 0x55f27fc6774e <unknown>
#4 0x55f27fc65ae6 <unknown>
#5 0x55f27fc653aa <unknown>
#6 0x55f27fc5b8e3 <unknown>
#7 0x55f27fc5b3c3 <unknown>
#8 0x55f27fc5b369 <unknown>
#9 0x55f27fca0143 <unknown>
#10 0x55f27fc9fa51 <unknown>
#11 0x55f27fc5aa07 <unknown>
#12 0x55f27fc59d1e <unknown>
#13 0x55f27fc5a7f1 <unknown>
#14 0x55f2802b0c5c <unknown>
#15 0x55f2802af475 <unknown>
#16 0x55f28029a7f8 <unknown>
#17 0x55f2802b00ca <unknown>
#18 0x55f2802833f9 <unknown>
#19 0x55f2802d8848 <unknown>
#20 0x55f2802d89e5 <unknown>
#21 0x55f2802eca43 <unknown>
#22 0x7f75a589cb84 <unknown>
#23 0x7f75a5929ecc <unknown>

```

- 2026-10-31T05:33:20.192+08:00 點發送鈕失敗。錯誤原文（腳本只留下第一行）：

```
Message: element click intercepted: Element <button class="btn-send" onclick="sendMessage()">...</button> is not clickable at point (795, 859). Other element would receive the click: <label style="display:block;margin-bottom:.8rem;font-size:.82rem;line-height:1.5;">...</label>
```


勾選說明並按「先聊聊」之後（2026-10-31T05:33:20.526+08:00 之後），輸入框可以輸入，發送鈕可以點。

### 空白點發送

- 送出方式：點「發送」
- 準備送出的字串原文：
```

```

- 送出當下輸入框實際 value 原文：
```

```

- 送出時間：2026-10-31T05:33:21.603+08:00
- 結果時間：2026-10-31T05:33:22.957+08:00。氣泡數仍為 1（沒有新增使用者訊息，也沒有 AI 回覆）。輸入框事後 value 原文：
```

```

- 等待中：沒有出現。
- 畫面上沒有新的錯誤訊息。狀態燈仍是「尚未接上 AI」。

### 只有空白字元按 Enter

- 送出方式：在輸入框按 Enter
- 準備送出的字串原文：
```
   	   
```

- 送出當下輸入框實際 value 原文：
```
   
```

- 送出時間：2026-10-31T05:33:23.093+08:00
- 結果時間：2026-10-31T05:33:24.424+08:00。氣泡數仍為 1（沒有新增使用者訊息，也沒有 AI 回覆）。輸入框事後 value 原文：
```
   
```

- 等待中：沒有出現。
- 畫面上沒有新的錯誤訊息。狀態燈仍是「尚未接上 AI」。

空白那次，定位鍵（Tab）沒有留在輸入框裡：準備送出的字串含 Tab，實際 value 只有三個空格 U+0020。Enter 之後氣泡數仍是 1，這三個空格還留在輸入框。

## 逐則對話

### 第 1 則　一般問候（Enter）

- 使用者輸入原文：
```
你好
```

- 使用者氣泡出現時間：2026-10-31T05:33:24.574+08:00
- 等待中出現時間：2026-10-31T05:33:24.575+08:00。出現當下文字原文：
```

```

- 等待中文字更新時間：2026-10-31T05:33:24.597+08:00。原文：
```
安啦正在認真傾聽中...💭
```

- 等待中消失時間：2026-10-31T05:33:24.600+08:00。消失前文字原文：
```
安啦正在認真傾聽中...💭
```

- 等待中持續時間：25 毫秒（消失時間減出現時間）。
- AI／畫面回覆完整原文：
```
（這個網站目前沒有接上 AI）抱歉，我現在沒辦法好好回覆你，請稍後再傳一次。如果現在有立即危險，請撥 119；想找人談可以打 1925，二十四小時都有人接。
```

- 回覆出現時間：2026-10-31T05:33:24.600+08:00
- 回覆來源：程式既有固定說明（未接上 AI）。不是本次新增的 mock，也沒有呼叫外部模型。

### 第 2 則　心情低落（點發送）

- 使用者輸入原文：
```
最近心情好低落，做什麼事都提不起勁。
```

- 使用者氣泡出現時間：2026-10-31T05:33:25.114+08:00
- 等待中出現時間：2026-10-31T05:33:25.114+08:00。出現當下文字原文：
```

```

- 等待中文字更新時間：2026-10-31T05:33:25.122+08:00。原文：
```
安啦正在認真傾聽中...💭
```

- 等待中消失時間：2026-10-31T05:33:25.141+08:00。消失前文字原文：
```
安啦正在認真傾聽中...💭
```

- 等待中持續時間：27 毫秒（消失時間減出現時間）。
- AI／畫面回覆完整原文：
```
（這個網站目前沒有接上 AI）抱歉，我現在沒辦法好好回覆你，請稍後再傳一次。如果現在有立即危險，請撥 119；想找人談可以打 1925，二十四小時都有人接。
```

- 回覆出現時間：2026-10-31T05:33:25.141+08:00
- 回覆來源：程式既有固定說明（未接上 AI）。不是本次新增的 mock，也沒有呼叫外部模型。

### 第 3 則　較長文字（點發送）

- 使用者輸入原文：
```
我想說長一點。這個禮拜每天都讀到半夜，數學段考還是沒有把握，同學都說很簡單，我問問題又怕被笑。回家以後也不太想說話，晚餐常常只吃幾口。我沒有想傷害自己，只是覺得很累，想有人聽我把這些話說完。如果可以的話，先不要叫我做呼吸練習，我現在只想把事情講清楚。
```

- 使用者氣泡出現時間：2026-10-31T05:33:25.696+08:00
- 等待中出現時間：2026-10-31T05:33:25.696+08:00。出現當下文字原文：
```

```

- 等待中文字更新時間：2026-10-31T05:33:25.705+08:00。原文：
```
安啦正在認真傾聽中...💭
```

- 等待中消失時間：2026-10-31T05:33:25.707+08:00。消失前文字原文：
```
安啦正在認真傾聽中...💭
```

- 等待中持續時間：11 毫秒（消失時間減出現時間）。
- AI／畫面回覆完整原文：
```
（這個網站目前沒有接上 AI）抱歉，我現在沒辦法好好回覆你，請稍後再傳一次。如果現在有立即危險，請撥 119；想找人談可以打 1925，二十四小時都有人接。
```

- 回覆出現時間：2026-10-31T05:33:25.707+08:00
- 回覆來源：程式既有固定說明（未接上 AI）。不是本次新增的 mock，也沒有呼叫外部模型。

### 第 4 則　求助關鍵字（點發送）

- 使用者輸入原文：
```
我不想活了
```

- 使用者氣泡出現時間：2026-10-31T05:33:26.244+08:00
- 等待中出現時間：2026-10-31T05:33:26.244+08:00。出現當下文字原文：
```

```

- 等待中文字更新時間：2026-10-31T05:33:26.255+08:00。原文：
```
安啦正在認真傾聽中...💭
```

- 等待中消失時間：2026-10-31T05:33:26.267+08:00。消失前文字原文：
```
安啦正在認真傾聽中...💭
```

- 等待中持續時間：23 毫秒（消失時間減出現時間）。
- AI／畫面回覆完整原文：
```
謝謝你願意跟我說這麼重的事。我想直接問你：你有想過結束自己的生命嗎？如果已經受傷、吃了藥或正要行動，請現在打 119 或 110；想找人談可以打 1925，二十四小時都有人接。我會在這裡，你也可以繼續說。
```

- 回覆出現時間：2026-10-31T05:33:26.267+08:00
- 回覆來源：程式既有本地安全文字（safety_reply）。狀態燈仍顯示尚未接上 AI，但這則不是「沒有接上 AI」那句固定說明。沒有呼叫外部模型。

### 第 5 則　後端停止後送出（點發送）

- 使用者輸入原文：
```
你還在嗎
```

- 使用者氣泡出現時間：2026-10-31T05:33:30.521+08:00
- 等待中出現時間：2026-10-31T05:33:30.521+08:00。出現當下文字原文：
```

```

- 等待中文字更新時間：2026-10-31T05:33:30.522+08:00。原文：
```
安啦正在認真傾聽中...💭
```

- 等待中消失時間：2026-10-31T05:33:30.525+08:00。消失前文字原文：
```
安啦正在認真傾聽中...💭
```

- 等待中持續時間：4 毫秒（消失時間減出現時間）。
- AI／畫面回覆完整原文：
```
訊息送出時發生問題：Failed to fetch。剛才打的字已放回輸入框，可以再按一次送出；若現在有立即危險，請直接撥打 119 或找身邊的大人。
```

- 回覆出現時間：2026-10-31T05:33:30.525+08:00
- 回覆來源：前端 fetch 失敗後自己組的錯誤氣泡。後端已停止，沒有模型回覆。

第 4 則送出後，緊急求助全螢幕面板 `#urgentHelpPanel` 的 hidden 仍為 true，畫面上沒有另外展開那塊面板。求助電話寫在回覆句子裡。沒有點電話連結。

第 1 到第 3 則送出後，狀態燈文字都仍是「尚未接上 AI」。

## 新對話與結束清除

- 2026-10-31T05:33:26.750+08:00 畫面上找得到的「結束」或「清除」字樣，只有危機回覆內文，沒有名為「結束清除」的按鈕。開始新對話按鈕文字：「開始新對話」。
- 2026-10-31T05:33:26.809+08:00 確認框原文：
```
要開始新對話嗎？

剛才的對話會從這個網站的暫存刪除，安啦也不會再記得。已經送到真人工作臺的資料不會被刪除。

如果現在有立即危險，請先撥 119，或打 1925 安心專線。
```

- 按下確定後頁面重新載入。2026-10-31T05:33:28.030+08:00 氣泡數為 1，只剩開場白，先前四則對話不在畫面上。輸入框 value 原文：
```

```

- 開場白原文：
```

              哈囉少年仔！我是「安啦會客室」的 AI 陪伴夥伴。👋
              無論是段考讀不完、跟朋友有小摩擦、在學校覺得孤單，或是家裡的壓力，
              在這裡你可以放鬆把心事說出來，按下方麥克風 🎙️ 也可以直接用說的喔！
              我會先聽你說；如果現在有立即危險，請直接使用下方的電話求助。
              
                
              
            
```

- 伺服器有 `POST /api/chat/reset`，狀態 200（見下方 log）。

## 後端停止後的錯誤

- 停止方式：對本機 tmux 工作階段送出 Ctrl+C，接著結束本機 python app.py。沒有動到 ngrok 或正式網站。
- 2026-10-31T05:33:30.432+08:00 對 http://127.0.0.1:5000/health 的 curl 等待狀態碼是 1792。這是退出碼 7（連線被拒）的 wait status（7×256）。
- 畫面錯誤氣泡就是上面第 5 則的回覆原文。
- 2026-10-31T05:33:30.849+08:00 輸入框被放回的原文：
```
你還在嗎
```

- 狀態燈仍是「尚未接上 AI」。離線橫幅文字：''。

## 瀏覽器 console 原文

共 3 筆。全文如下：

- 2026-10-31T05:33:17.800+08:00　INFO　http://127.0.0.1:5000/ - Banner not shown: beforeinstallpromptevent.preventDefault() called. The page must call beforeinstallpromptevent.prompt() to show the banner.
- 2026-10-31T05:33:28.028+08:00　INFO　http://127.0.0.1:5000/ - Banner not shown: beforeinstallpromptevent.preventDefault() called. The page must call beforeinstallpromptevent.prompt() to show the banner.
- 2026-10-31T05:33:30.839+08:00　SEVERE　http://127.0.0.1:5000/api/chat - Failed to load resource: net::ERR_CONNECTION_REFUSED

## 伺服器 log 原文

檔案另存：artifacts/chat-test/server.log。下面是該檔全文。時區是行程裡的 Asia/Taipei。沒有 Python Traceback，也沒有 4xx／5xx。唯一的 WARNING 是 Flask 開發伺服器提示。ANSI 顏色碼照檔案保留。

```
 * Serving Flask app 'app'
 * Debug mode: off
[31m[1mWARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.[0m
 * Running on http://127.0.0.1:5000
[33mPress CTRL+C to quit[0m
127.0.0.1 - - [31/Oct/2026 05:31:30] "GET /health HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:04] "GET / HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:04] "GET /static/js/theme.js?v=bae244d219 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:04] "GET /static/css/style.css?v=766c4c6a0b HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:04] "GET /static/css/themes.css?v=d379926365 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:04] "GET /static/js/referral.js?v=b50d50a1b3 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:04] "GET /static/js/app.js?v=4b23001b18 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:04] "GET /static/js/school_referral.js?v=0f626be3aa HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:04] "GET /static/js/checkin.js?v=138998eeb8 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:04] "GET /static/js/pwa.js?v=bce8d3a627 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /manifest.json HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /api/chat/state HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /api/tts/voices HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /api/status?probe=1 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /sw.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/icons/icon-192.png HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "[36mGET /static/icons/icon-192.png HTTP/1.1[0m" 304 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/css/style.css HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /offline HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/offline.html HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/css/themes.css HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/js/referral.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/js/app.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/js/school_referral.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/js/checkin.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/js/theme.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/js/pwa.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /manifest.json HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/manifest.json HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/icons/icon-192.png HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/icons/icon-maskable-192.png HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/icons/icon-512.png HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/icons/icon-maskable-512.png HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:05] "GET /static/icons/apple-touch-icon.png HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET / HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/css/style.css?v=766c4c6a0b HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/css/themes.css?v=d379926365 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/js/app.js?v=4b23001b18 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/js/referral.js?v=b50d50a1b3 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/js/theme.js?v=bae244d219 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/js/school_referral.js?v=0f626be3aa HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/js/pwa.js?v=bce8d3a627 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /manifest.json HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/js/checkin.js?v=138998eeb8 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /api/chat/state HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /api/tts/voices HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /api/status?probe=1 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/icons/icon-192.png HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "[36mGET /static/icons/icon-192.png HTTP/1.1[0m" 304 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /sw.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/offline.html HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /offline HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/css/style.css HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/css/themes.css HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/js/referral.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/js/app.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/js/school_referral.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/js/checkin.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/js/theme.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/manifest.json HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/js/pwa.js HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /manifest.json HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/icons/icon-512.png HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/icons/icon-192.png HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/icons/icon-maskable-192.png HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/icons/icon-maskable-512.png HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:16] "GET /static/icons/apple-touch-icon.png HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:20] "POST /api/onboarding HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:24] "POST /api/chat HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:25] "POST /api/chat HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:25] "POST /api/chat HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "POST /api/chat HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "POST /api/chat/reset HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "GET / HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "[36mGET /static/css/style.css?v=766c4c6a0b HTTP/1.1[0m" 304 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "[36mGET /static/css/themes.css?v=d379926365 HTTP/1.1[0m" 304 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "[36mGET /static/js/theme.js?v=bae244d219 HTTP/1.1[0m" 304 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "[36mGET /static/js/app.js?v=4b23001b18 HTTP/1.1[0m" 304 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "[36mGET /static/js/referral.js?v=b50d50a1b3 HTTP/1.1[0m" 304 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "[36mGET /static/js/school_referral.js?v=0f626be3aa HTTP/1.1[0m" 304 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "[36mGET /static/js/checkin.js?v=138998eeb8 HTTP/1.1[0m" 304 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "[36mGET /static/js/pwa.js?v=bce8d3a627 HTTP/1.1[0m" 304 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "[36mGET /manifest.json HTTP/1.1[0m" 304 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "GET /api/status?probe=1 HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "GET /api/tts/voices HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "GET /api/chat/state HTTP/1.1" 200 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "[36mGET /static/icons/icon-192.png HTTP/1.1[0m" 304 -
127.0.0.1 - - [31/Oct/2026 05:33:26] "[36mGET /static/icons/icon-192.png HTTP/1.1[0m" 304 -
```

後端在第 5 則送出前已停止，所以 log 裡沒有那一次 `POST /api/chat`。

## 截圖

- artifacts/chat-test/01-loaded.png
- artifacts/chat-test/02-before-onboarding.png
- artifacts/chat-test/03-after-onboarding.png
- artifacts/chat-test/04-empty-send.png
- artifacts/chat-test/05-whitespace-enter.png
- artifacts/chat-test/06-greeting.png
- artifacts/chat-test/07-low-mood.png
- artifacts/chat-test/08-long-text.png
- artifacts/chat-test/09-crisis-keyword.png
- artifacts/chat-test/11-after-new-conversation.png
- artifacts/chat-test/12-backend-stopped.png

同目錄另有原始事件 artifacts/chat-test/events.json。
