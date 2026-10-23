<p align="center">
  <img src="fpSup/assets/fpsup-logo.png" width="180" alt="fpSup">
</p>

<h3 align="center">Research and development guide for SIGMA fp firmware Ver.5.02</h3>

<p align="center">
  The fp L firmware is very similar, so this guide is useful there too;<br>
  but memory addresses differ, so the cards and code here <b>will not work as-is on the fp L or other firmware versions</b>.<br>
  Developers working on other cameras may still find <a href="JOURNEY.md">the development story and lessons</a> useful.
</p>

<p align="center">
  <a href="https://ijigen.github.io/fpSup/"><img src="https://img.shields.io/badge/fpSup-website-e0405e?style=flat" alt="fpSup website"></a>
  <a href="https://ijigen.github.io/fpSup/tools/card-composer/"><img src="https://img.shields.io/badge/fpSup--Merge-build%20a%20card-e8c400?style=flat" alt="fpSup-Merge"></a>
  <a href="https://discord.gg/XeFK5zNZpT"><img src="https://img.shields.io/badge/Discord-join-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://www.youtube.com/@fp-sup"><img src="https://img.shields.io/badge/YouTube-showcase-FF0000?style=flat&logo=youtube&logoColor=white" alt="YouTube"></a>
  <a href="https://ko-fi.com/fpsup"><img src="https://img.shields.io/badge/Ko--fi-support-FF5E5B?style=flat&logo=kofi&logoColor=white" alt="Ko-fi"></a>
</p>

<p align="center">
  <b>EN</b> / <a href="README.zh-CN.md">中</a> / <a href="README.zh-TW.md">繁</a>
</p>

> [!TIP]
> **Lost?** This repo is for developers.
> **To download fpSup → [the fpSup website](https://ijigen.github.io/fpSup/)** (downloads, installation, a guide for every tool),
> or go straight to **[fpSup-Merge](https://ijigen.github.io/fpSup/tools/card-composer/)**, pick your tools and download a whole card.
> Questions, bug reports, or just to chat → **[Discord](https://discord.gg/XeFK5zNZpT)**

**fp L port in development:** [shared-code approach and status](fpSup/docs/FPL_PORT.md).
Development shell, RAM transfers and card transfers are verified on fp L 3.02;
the downloadable product cards still target fp 5.02. See [development tools](fpSup/docs/FPL_TOOLS.md).

---

## 🛠️ How this repo helps you build

<table>
<tr>
<td width="33%" valign="top">

### 🔌 USB Shell
Lets your computer talk to the camera directly: read and write memory, call firmware functions, press buttons, take screenshots, move files fast.

**No pulling the card, no endless button pressing.**

</td>
<td width="33%" valign="top">

### 📚 Research notes
Facts about the firmware, sensor, interfaces and storage are already written down, **so you don't start decompiling from zero.**

Want to know the hardware limits → the explainers and simulators on the [website's research page](https://ijigen.github.io/fpSup/research.html).

</td>
<td width="33%" valign="top">

### 🤖 AI Skills
Manuals written for AI, so **your AI** can drive the camera, build cards and edit menus.

</td>
</tr>
</table>

**You describe the feature you want → your AI reads the notes and tests on the camera over USB → together you build your own sup.** [→ Development guide](#-development-guide)

---

## 💭 Philosophy

Developing with AI taught me how valuable the research process itself is.
So I'm sharing not just the results, but the **knowledge, tools, methods and AI Skills** gathered along the way.

> [!IMPORTANT]
> **Please treat all of this as reference, not truth.**
> My AI has made many mistakes, and some of them may still be in my research notes or Skills.
> Be careful not to let my AI's unverified information pollute your own development environment.

### 🌱 Development and collaboration

Everyone should develop in whatever way feels most comfortable — me included.
Not everyone needs to work on the same project, or follow the same rules just to make things easier to manage.

I think times have changed: **the cost of projects understanding and integrating with each other has dropped enormously in the AI era.**
Rather than everyone tied together, moving toward a single goal,
maybe it's better to let everyone work freely and let AI absorb the cost of understanding each other.
Even when people do the same research, they may find different details.
I'm not sure, but I think this kind of growing through each other might take us further.

I encourage voluntary sharing and learning from each other, but everyone has the right to decide how much to share.

- 🐛 **PRs that fix mistakes, fix bugs or improve things are welcome.**
- 🌟 For new features and independent Sup modules, I generally encourage developers to maintain their own projects.
- 🧩 With the author's permission, I may include their work in **fpSup-Merge**, always with credit.

**Every developer deserves their own stage to shine.**
My goal isn't to collect everyone's work under my name, but to help more people discover and enjoy what others have made.

### 🤝 Connecting people

I don't know how long fpSup will stay meaningful.

AI is moving so fast that in a few years much of this research may seem trivial.
People may solve these problems just by talking to their own AI.
And that's completely fine.

Because along the way, I found that what matters to me isn't only the technology.
The experiments, the failures, the discoveries, and above all the people I met through this project have become precious to me.
Even if the technology becomes obsolete, those experiences and connections will stay with me.

**I want to create connections between people. That's why I started a community 👉 [Discord](https://discord.gg/XeFK5zNZpT)**

**— bei / 夏曉雨 / ijigen ❤️** (all of these are me, just different names 😆)

---

## 🔓 How I found the way in

#### 🎥 The starting point

I often shoot alone, as both the camera operator and the subject, so I really needed reliable autofocus.
Hyperfocal, PDMOVIE Live Air, DJI Focus Pro — I tried them all, and none satisfied me.

So in my spare time after work I built [sigma-fp-bridge](https://github.com/ijigen/sigma-fp-bridge): focus control over PTP, face detection, focus distance prediction.
I stayed up testing almost every night, and the AI would even use voice to tell me where to stand so it could test on me.

#### 💀 A dead end

Just when I thought I was nearly there, I took it out for a real shoot for the first time and pressed record —

> ### PTP focus stopped completely while recording.

After all that testing, I had never once thought to test whether it worked during recording. I felt like the biggest idiot in the world. 😱

#### 🔍 Opening up the firmware

I couldn't let it go. I was convinced SIGMA's engineers must have left hidden commands somewhere, so I had AI take the firmware apart and decompile it.
PTP was confirmed to be a dead end, but along the way we found the gimbal interface, factory test points, and something called `AutoRun.txt`.

The AI kept thinking it was nothing, just a simple scripting language.
Until I noticed **`mem set`** among the shell commands, which can write to any memory address — from my past reverse-engineering experience, I knew instinctively I'd struck gold.

> ### 🗝️ This was the way in.

#### 🌀 Build something big enough

I posted a few small toys to the community, and almost nobody noticed.
People hadn't yet realised that this discovery proved everything could be changed.
So I spent over a month and countless sleepless nights building **fpSup-GYRO**, and released the development tools I'd made along the way.

And just as I was about to reach the Open Gate milestone, developer Vitaly Li announced his success first.

> I always knew I could have just switched cameras, or even used a phone.
> But I really love the fp's design, so I stubbornly stuck with it. 😅

I think this love for the fp is exactly why, small as its user base is, excellent work by developers has sprung up like mushrooms after rain.

📖 **The fuller story and lessons learned → [JOURNEY.md](JOURNEY.md)**
It may help you, especially if you want to start from scratch on another camera.

---

## 🧭 Development guide

> [!WARNING]
> This repo contains experimental firmware research and unofficial modifications.
> Some code may be incomplete, untested or even dangerous. Using it may cause failed recordings, data loss, broken settings, or even an unusable camera.
> This project is not affiliated with or endorsed by SIGMA Corporation.
> **Use at your own risk.**

### 💡 How to start a new feature

| | |
|:-:|---|
| **1️⃣ Know what you want** | What do you want the fp to do? Research direction comes from needs, not from an index. |
| **2️⃣ Check the hardware limits** | Use the [website's research page](https://ijigen.github.io/fpSup/research.html) to judge whether it can work:<br>・Are the resolution and frame rate reasonable, and does the data rate (MB/s) fit the storage?<br>・What hardware lossless compression can and can't do<br>・What SIGMA's existing sensor modes can already do<br>・The ISP flow: which stages a frame passes from the sensor to CinemaDNG |
| **3️⃣ Hand it to your AI** | Have it read [`INDEX.md`](INDEX.md), the relevant `projects/<name>/` and `.claude/skills/`, work out what is already known and what's missing, then verify on the camera together. |

### 🎒 What you need

- 📷 A SIGMA fp on **firmware Ver.5.02** (fp L can use this as reference, but the cards won't work directly)
- 🔌 A USB-C cable and an SD card
- 💻 A Mac (the USB Shell host tools are currently developed on macOS)
- 🤖 An AI coding assistant that can read files and run commands (Codex, Claude Code)
- 🔍 **The firmware is not here**: this repo does not include SIGMA's firmware or any decompiled output. Whether to analyse the firmware yourself, and the legal risks that come with it (laws and SIGMA's terms of use vary by place), is your own decision and responsibility.

### 🚀 Three steps to get going

| Step | What to do | Reference |
|---|---|---|
| **1. Connect the USB Shell** | Build a card with USB Shell in fpSup-Merge → plug in USB → the host tools can read/write memory, press buttons, take screenshots | skill `fp-camera-control`, `fp-usb-shell` |
| **2. Let your AI take over** | Have it read `INDEX.md` and `.claude/skills/` first.<br>⚠️ **These were written by my AI and contain mistakes.** Verify important conclusions yourself. | |
| **3. Build your own sup** | Build cards, test changes, release | `fpSup/BUILDING.md`, skill `fp-merged-card` |

### ⚠️ Before you touch the camera

- Once your feature is done, run it in emulation before writing it to a card and testing on the camera → skill `fp-unicorn-emulation`
- Be careful writing to the camera's settings area: it survives power-off. Past analysis is in [`research/SETTINGS_AREA_FIRST_RULE.md`](research/SETTINGS_AREA_FIRST_RULE.md) (reference only).
- Camera frozen: read the card first (data written by hooks is still there), then pull the battery for a cold start.

<details>
<summary><b>📁 How this repo is laid out</b></summary>

```
README*.md      ← you are here (EN / 中 / 繁)
JOURNEY*.md     ← the full story
INDEX.md        ← master research index: find any topic from here
research/       ← facts about the camera itself (firmware, sensor, interfaces, storage…), true for any project
projects/       ← development trees for each sup and experiment: source, test cards, validation logs, failures
fpSup/          ← website, released cards (releases/), release source of each sup, fpSup-Merge
.claude/skills/ ← manuals for AI (driving the camera, calling firmware functions, building cards, editing menus…)
```

</details>

<details>
<summary><b>📦 Only want part of it?</b> (the whole repo is about 14 GB)</summary>

For just the source:

```sh
git clone --filter=blob:none --sparse https://github.com/ijigen/fpSup.git
cd fpSup && git sparse-checkout set fpSup .claude
```

Before committing, turn on the pre-commit check (it stops firmware or decompiler output from slipping in):

```sh
git config core.hooksPath .githooks
```

</details>
