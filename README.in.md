<p align="center">
  <img src="https://aiutils.io/images/elidia-lockup-dark.png" alt="Elidia Agent" >
</p>



<p align="center">
  <a href="https://pypi.org/project/elidia-agent-cli/"><img src="https://img.shields.io/pypi/v/elidia-agent-cli?style=for-the-badge&label=PyPI&color=3775A9" alt="PyPI"></a>
  <a href="https://aiutils.io/elidia"><img src="https://img.shields.io/badge/Docs-aiutils.io-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="https://developer.aiutils.io"><img src="https://img.shields.io/badge/Developer%20Console-developer.aiutils.io-3775A9?style=for-the-badge" alt="Developer Console"></a>
  <a href="https://aiutils.io"><img src="https://img.shields.io/badge/Powered%20by-Elidia%20Technology-blueviolet?style=for-the-badge" alt="Powered by Elidia Technology"></a>
  <a href="README.md"><img src="https://img.shields.io/badge/Lang-English-lightgrey?style=for-the-badge" alt="English"></a>
</p>

**Elidia Agent** आपके टर्मिनल और मैसेजिंग ऐप्स के लिए एक बहु-प्लेटफ़ॉर्म AI एजेंट है। यह [AiUtils.io](https://aiutils.io) इकोसिस्टम का हिस्सा है और **Elidia Technology Pvt. Ltd.** द्वारा संचालित है।

इसे उसी मॉडल प्रोवाइडर के साथ उपयोग करें जिसके साथ आप पहले से काम करते हैं — [Elidia Portal](https://developer.aiutils.io), [OpenRouter](https://openrouter.ai) (200+ मॉडल), [NovitaAI](https://novita.ai), [NVIDIA NIM](https://build.nvidia.com), [Xiaomi MiMo](https://platform.xiaomimimo.com), [z.ai/GLM](https://z.ai), [Kimi/Moonshot](https://platform.moonshot.ai), [MiniMax](https://www.minimax.io), [Hugging Face](https://huggingface.co), OpenAI, या अपना खुद का endpoint। `elidia model` से स्विच करें — कोई कोड बदलाव नहीं, कोई लॉक-इन नहीं।

## ✨ विशेषताएँ

| | |
| --- | --- |
| 🖥️ **टर्मिनल इंटरफ़ेस** | मल्टीलाइन एडिटिंग, slash-command ऑटोकम्प्लीट, कन्वर्सेशन हिस्ट्री और स्ट्रीमिंग टूल आउटपुट के साथ इंटरैक्टिव TUI। |
| 📱 **मैसेजिंग प्लेटफ़ॉर्म** | Telegram, Discord, Slack, WhatsApp, Signal और CLI — सब एक ही गेटवे से। |
| 🧠 **मेमोरी और स्किल्स** | सत्रों के बीच याद रखता है, पुनः उपयोग योग्य स्किल्स बनाता है, और [agentskills.io](https://agentskills.io) ओपन स्टैंडर्ड के साथ काम करता है। |
| ⏰ **शेड्यूल्ड टास्क** | दैनिक रिपोर्ट, बैकअप और ऑडिट के लिए बिल्ट-इन cron — सादी भाषा में बताइए। |
| 🧩 **सब-एजेंट्स** | समानांतर काम के लिए आइसोलेटेड सब-एजेंट स्पॉन करें। |
| ☁️ **लचीली डिप्लॉयमेंट** | local, Docker, SSH, या serverless बैकएंड (Modal, Daytona) पर चलाएँ। |
| 🔬 **रिसर्च टूलिंग** | tool-calling मॉडल्स के प्रशिक्षण के लिए बैच ट्रैजेक्टरी जनरेशन और कम्प्रेशन। |

---

## 🚀 इंस्टॉल करें

**Python 3.11–3.13** आवश्यक है।

```bash
pip install elidia-agent-cli
```

आइसोलेटेड टूल एनवायरनमेंट पसंद है? [uv](https://docs.astral.sh/uv/) (अनुशंसित) या [pipx](https://pipx.pypa.io/) का उपयोग करें:

```bash
uv tool install elidia-agent-cli
# या
pipx install elidia-agent-cli
```

एक ही बार में सभी वैकल्पिक बैकएंड (मैसेजिंग प्लेटफ़ॉर्म, वेब सर्च, इमेज जनरेशन, TTS और भी बहुत कुछ) लाने के लिए:

```bash
pip install "elidia-agent-cli[all]"
```

फिर शुरू करें:

```bash
elidia              # चैट करना शुरू करें
```

> [!NOTE]
> **Android / Termux:** [Termux गाइड](docs/termux.md) देखें। Termux पर वह क्यूरेटेड एक्स्ट्रा इंस्टॉल करें जो Android-असंगत वॉयस डिपेंडेंसी से बचता है:
>
> ```bash
> pip install "elidia-agent-cli[termux]"
> ```

पूरी इंस्टॉल जानकारी: [docs/installation.md](docs/installation.md)।

---

## 🏁 शुरुआत करें

```bash
elidia              # इंटरैक्टिव CLI — बातचीत शुरू करें
elidia model        # अपना LLM प्रोवाइडर और मॉडल चुनें
elidia tools        # कौन-से टूल सक्षम हैं, कॉन्फ़िगर करें
elidia config set   # अलग-अलग कॉन्फ़िग वैल्यू सेट करें
elidia gateway      # मैसेजिंग गेटवे शुरू करें (Telegram, Discord आदि)
elidia setup        # पूरा सेटअप विज़ार्ड चलाएँ
elidia claw migrate # OpenClaw से माइग्रेट करें
elidia update       # नवीनतम संस्करण में अपडेट करें
elidia doctor       # किसी भी समस्या का निदान करें
```

📖 **[पूर्ण दस्तावेज़ →](https://aiutils.io/elidia)** — या नीचे दिए गए in-repo गाइड देखें।

---

## 🎁 सब कुछ एक ही सब्सक्रिप्शन में — Elidia Portal

Elidia किसी भी प्रोवाइडर के साथ काम करता है। यदि आप मॉडल, वेब सर्च, इमेज जनरेशन, TTS और क्लाउड ब्राउज़र के लिए अलग-अलग API keys नहीं संभालना चाहते, तो **[Elidia Portal](https://developer.aiutils.io)** एक सब्सक्रिप्शन में सब कवर कर देता है:

* **300+ LLMs** — `/model <name>` का उपयोग करके अपनी पसंद का कोई भी मॉडल चुनें।
* **1400+ जनरेटिव मॉडल्स** — अपनी पसंद का मॉडल चुनकर इमेज, वीडियो, ऑडियो और 3D कंटेंट जनरेट करें।
* **टूल गेटवे** — वेब सर्च (Firecrawl), इमेज/वीडियो/ऑडियो/3D जनरेशन, टेक्स्ट-टू-स्पीच (OpenAI), क्लाउड ब्राउज़र (Browser Use) — सभी सुविधाएँ आपकी सब्सक्रिप्शन के माध्यम से एक ही जगह से उपलब्ध।


फ्रेश इंस्टॉल से बस एक कमांड:

```bash
elidia setup --portal
```

यह OAuth के ज़रिए साइन इन करता है, Elidia को आपका प्रोवाइडर सेट करता है, और टूल गेटवे चालू करता है। कभी भी `elidia portal info` से जाँचें कि क्या कनेक्ट है। पूरी जानकारी: [docs/elidia-portal.md](docs/elidia-portal.md) और [docs/tool-gateway.md](docs/tool-gateway.md)।

आप कभी भी, किसी भी टूल के लिए अपनी keys ला सकते हैं — गेटवे per-backend है, all-or-nothing नहीं।

---

## 🧭 CLI बनाम मैसेजिंग — त्वरित संदर्भ

Elidia के दो प्रवेश बिंदु हैं: `elidia` से टर्मिनल UI शुरू करें, या गेटवे चलाकर Telegram, Discord, Slack, WhatsApp, Signal या Email से बात करें। कई slash-commands दोनों में समान रूप से काम करते हैं।

| कार्य | CLI | मैसेजिंग प्लेटफ़ॉर्म |
| --- | --- | --- |
| चैट शुरू करें | `elidia` | `elidia gateway setup` + `elidia gateway start` चलाएँ, फिर बॉट को मैसेज भेजें |
| नई बातचीत शुरू करें | `/new` या `/reset` | `/new` या `/reset` |
| मॉडल बदलें | `/model [provider:model]` | `/model [provider:model]` |
| पर्सनैलिटी सेट करें | `/personality [name]` | `/personality [name]` |
| पिछला टर्न रीट्राई / अनडू करें | `/retry`, `/undo` | `/retry`, `/undo` |
| कॉन्टेक्स्ट कम्प्रेस करें / उपयोग देखें | `/compress`, `/usage`, `/insights [--days N]` | `/compress`, `/usage`, `/insights [days]` |
| स्किल्स ब्राउज़ करें | `/skills` या `/<skill-name>` | `/<skill-name>` |
| मौजूदा काम रोकें | `Ctrl+C` या नया मैसेज भेजें | `/stop` या नया मैसेज भेजें |
| प्लेटफ़ॉर्म-विशिष्ट स्थिति | `/platforms` | `/status`, `/sethome` |

पूरी कमांड सूची के लिए [CLI गाइड](docs/cli.md) और [मैसेजिंग गेटवे गाइड](docs/messaging.md) देखें।

---

## 📚 दस्तावेज़

सभी दस्तावेज़ **[aiutils.io/elidia](https://aiutils.io/elidia)** पर और इस रिपॉज़िटरी के [`docs/`](docs/README.md) फ़ोल्डर में Markdown फ़ाइलों के रूप में उपलब्ध हैं:

| अनुभाग | क्या शामिल है |
| --- | --- |
| [इंस्टॉलेशन](docs/installation.md) | Linux, macOS, WSL2, Windows, Termux |
| [क्विकस्टार्ट](docs/quickstart.md) | इंस्टॉल → सेटअप → 2 मिनट में पहली बातचीत |
| [CLI उपयोग](docs/cli.md) | कमांड्स, कीबाइंडिंग्स, पर्सनैलिटीज़, सत्र |
| [कॉन्फ़िगरेशन](docs/configuration.md) | कॉन्फ़िग फ़ाइल, प्रोवाइडर्स, मॉडल, सभी विकल्प |
| [मैसेजिंग गेटवे](docs/messaging.md) | Telegram, Discord, Slack, WhatsApp, Signal, Home Assistant |
| [सुरक्षा](docs/security.md) | कमांड अनुमोदन, DM पेयरिंग, कंटेनर आइसोलेशन |
| [टूल्स और टूलसेट्स](docs/tools.md) | 40+ टूल, टूलसेट सिस्टम, टर्मिनल बैकएंड |
| [स्किल्स सिस्टम](docs/skills.md) | प्रोसीजरल मेमोरी, स्किल्स हब, स्किल्स बनाना |
| [मेमोरी](docs/memory.md) | पर्सिस्टेंट मेमोरी, यूज़र प्रोफ़ाइल, बेस्ट प्रैक्टिस |
| [MCP इंटीग्रेशन](docs/mcp.md) | विस्तारित क्षमताओं के लिए कोई भी MCP सर्वर जोड़ें |
| [Cron शेड्यूलिंग](docs/cron.md) | प्लेटफ़ॉर्म डिलीवरी के साथ शेड्यूल्ड टास्क |
| [कॉन्टेक्स्ट फ़ाइलें](docs/context-files.md) | प्रोजेक्ट कॉन्टेक्स्ट जो हर बातचीत को आकार देता है |
| [Elidia Portal](docs/elidia-portal.md) | एक सब्सक्रिप्शन, 1400+ LLMs & मॉडल, टूल गेटवे |
| [OpenClaw से माइग्रेट करना](docs/migrate-from-openclaw.md) | सेटिंग्स, यादें, स्किल्स और API keys इम्पोर्ट करें |
| [आर्किटेक्चर](docs/architecture.md) | प्रोजेक्ट संरचना, एजेंट लूप, मुख्य क्लासेस |
| [योगदान](docs/contributing.md) | डेवलपमेंट सेटअप, PR प्रक्रिया, कोड स्टाइल |
| [CLI संदर्भ](docs/cli-commands.md) | सभी कमांड्स और फ़्लैग |
| [एनवायरनमेंट वेरिएबल्स](docs/environment-variables.md) | संपूर्ण env var संदर्भ |

---

## 🔄 OpenClaw से माइग्रेट करना

यदि आप OpenClaw से आ रहे हैं, तो Elidia आपकी सेटिंग्स, यादें, स्किल्स और API keys इम्पोर्ट कर सकता है।

**पहली बार सेटअप के दौरान:** सेटअप विज़ार्ड (`elidia setup`) `~/.openclaw` का पता लगाता है और कॉन्फ़िगरेशन शुरू होने से पहले माइग्रेट करने का विकल्प देता है।

**इंस्टॉल के बाद कभी भी:**

```bash
elidia claw migrate              # इंटरैक्टिव माइग्रेशन (पूर्ण प्रीसेट)
elidia claw migrate --dry-run    # देखें कि क्या माइग्रेट होगा
elidia claw migrate --preset user-data   # बिना secrets के माइग्रेट करें
elidia claw migrate --overwrite  # मौजूदा टकरावों को ओवरराइट करें
```

क्या इम्पोर्ट होता है:

- **SOUL.md** — पर्सोना फ़ाइल
- **यादें** — MEMORY.md और USER.md एंट्रीज़
- **स्किल्स** — यूज़र-निर्मित स्किल्स → `~/.elidia/skills/openclaw-imports/`
- **कमांड अलाउलिस्ट** — अनुमोदन पैटर्न
- **मैसेजिंग सेटिंग्स** — प्लेटफ़ॉर्म कॉन्फ़िग, अनुमत यूज़र्स, वर्किंग डायरेक्टरी
- **API keys** — अलाउलिस्टेड secrets (Telegram, OpenRouter, OpenAI, Anthropic, ElevenLabs)
- **TTS एसेट्स** — वर्कस्पेस ऑडियो फ़ाइलें
- **वर्कस्पेस निर्देश** — AGENTS.md (`--workspace-target` के साथ)

पूरी गाइड के लिए [docs/migrate-from-openclaw.md](docs/migrate-from-openclaw.md) देखें।

---

## 📦 रिपॉज़िटरी और रिलीज़

यह सार्वजनिक रिपॉज़िटरी Elidia Agent के **पैकेज्ड रिलीज़ और दस्तावेज़** होस्ट करती है। सोर्स कोड एक निजी रिपॉज़िटरी में विकसित होता है और [PyPI](https://pypi.org/project/elidia-agent-cli/) पर बिल्ड आर्टिफैक्ट्स के रूप में वितरित किया जाता है।

- **नवीनतम रिलीज़:** मौजूदा `.whl` और `.tar.gz` बिल्ड आर्टिफैक्ट्स के लिए [Releases](https://github.com/Elidia-Technology/elidia-agent/releases) पेज देखें।
- **दस्तावेज़:** [aiutils.io/elidia](https://aiutils.io/elidia)
- **डेवलपर कंसोल:** [developer.aiutils.io](https://developer.aiutils.io)
- **बग रिपोर्ट करें / फ़ीचर अनुरोध करें:** एक [Issue](https://github.com/Elidia-Technology/elidia-agent/issues) खोलें

योगदान का स्वागत है — कोड स्टाइल और PR प्रक्रिया के लिए [योगदान गाइड](docs/contributing.md) देखें। चूँकि यह रिपॉज़िटरी सोर्स कोड होस्ट नहीं करती, कृपया इसके विरुद्ध कोड PR खोलने के बजाय यहाँ issues उठाएँ।

---

## 🤝 समुदाय

- 💬 [Discord](https://discord.gg/AiUtils)
- 📚 [स्किल्स हब](https://agentskills.io)
- 🔌 [computer-use-linux](https://github.com/avifenesh/computer-use-linux) — Elidia और अन्य MCP होस्ट्स के लिए Linux डेस्कटॉप-कंट्रोल MCP सर्वर।
- 🔌 [ElidiaClaw](https://github.com/AaronWong1999/elidiaclaw) — कम्युनिटी WeChat ब्रिज: एक ही WeChat खाते पर Elidia Agent और OpenClaw चलाएँ।

---

## 📄 लाइसेंस

MIT — [LICENSE](LICENSE) देखें।

---

[Elidia Technology Pvt. Ltd.](https://aiutils.io) द्वारा ❤️ के साथ निर्मित — [AiUtils.io](https://aiutils.io) इकोसिस्टम का हिस्सा।
