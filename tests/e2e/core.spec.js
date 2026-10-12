const { test, expect } = require("@playwright/test");

async function mockYouTube(page) {
  await page.route("https://www.youtube.com/iframe_api", async route => {
    await route.fulfill({
      contentType: "application/javascript",
      body: `
        window.YT = {
          Player: function(id, options) {
            const api = {
              cueVideoById: function(){},
              seekTo: function(){},
              playVideo: function(){},
              pauseVideo: function(){},
              getCurrentTime: function(){ return 0; }
            };
            setTimeout(function(){
              if (options && options.events && options.events.onReady) {
                options.events.onReady({target: api});
              }
            }, 0);
            return api;
          }
        };
        setTimeout(function(){
          if (window.onYouTubeIframeAPIReady) {
            window.onYouTubeIframeAPIReady();
          }
        }, 0);
      `
    });
  });
}

test("core dictation flow, punctuation checking, export and restore", async ({ page }) => {
  await mockYouTube(page);
  await page.route("**/api/transcript?*", async route => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        video_id: "e2etest1",
        video_title: "Mock Video",
        language: "English",
        language_code: "en",
        is_generated: false,
        segmentation_version: "e2e-v1",
        items: [
          {
            text: "Hello, world!",
            start: 0,
            end: 1,
            duration: 1
          }
        ]
      })
    });
  });

  await page.goto("/");

  page.once("dialog", dialog => dialog.accept("E2E Learner"));
  await page.getByRole("button", { name: "+ 学习者" }).click();
  await expect(page.locator("#learnerSelect")).toContainText("E2E Learner");

  await page.locator("#url").fill("https://youtu.be/e2etest1");
  await page.getByRole("button", { name: "获取字幕并开始" }).click();
  await expect(page.locator("#status")).toContainText("已生成 1 个听写句子");

  await page.locator("#answer").fill("hello world");
  await page.locator("#answer").press("Enter");
  await expect(page.locator("#feedback")).toContainText("全部正确");

  await page.goto("/learning");
  await expect(page.getByRole("heading", { name: "学习中心" })).toBeVisible();
  await expect(page.locator("#sessions")).toContainText("Mock Video");

  const exported = await page.evaluate(async () => {
    const learnerId = localStorage.getItem("mediaDictationLearnerId");
    return fetch("/api/export?learner_id=" + encodeURIComponent(learnerId))
      .then(r => r.json());
  });
  expect(exported.ok).toBeTruthy();
  expect(exported.export_version).toBe(1);

  page.once("dialog", dialog => dialog.accept());
  await page.locator("#importFile").setInputFiles({
    name: "backup.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(exported))
  });
  await expect(page.locator("#learnerSelect")).toContainText("E2E Learner (2)");
});

test("word-card state resets and translation shortcuts work", async ({ page }) => {
  await mockYouTube(page);

  await page.route("**/api/transcript?*", async route => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        video_id: "wordstate1",
        video_title: "Word State",
        language: "English",
        language_code: "en",
        is_generated: false,
        segmentation_version: "e2e-v1",
        items: [
          {
            text: "Hello world again.",
            start: 0,
            end: 1,
            duration: 1
          }
        ]
      })
    });
  });

  await page.route("**/api/word-lookup", async route => {
    const body = route.request().postDataJSON();
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        word: body.word,
        normalized_word: String(body.word || "").toLowerCase(),
        translation: "释义-" + body.word,
        model: "e2e",
        provider: "test",
        service_tier: "",
        cached: false
      })
    });
  });

  await page.route("**/api/vocabulary", async route => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    const body = route.request().postDataJSON();
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        item: {
          id: 1,
          normalized_word: String(body.word || "").toLowerCase()
        }
      })
    });
  });

  await page.route("**/api/translate", async route => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        translation: "你好，世界。",
        model: "e2e",
        provider: "test",
        service_tier: ""
      })
    });
  });

  await page.goto("/");
  await page.locator("#url").fill("https://youtu.be/wordstate1");
  await page.getByRole("button", { name: "获取字幕并开始" }).click();
  await expect(page.locator("#status")).toContainText("已生成 1 个听写句子");

  await page.locator("#show").click();

  const words = page.locator(".word-token");
  await words.nth(0).click();
  await expect(page.locator("#addVocab")).toHaveText("加入生词本");
  await page.locator("#addVocab").click();
  await expect(page.locator("#addVocab")).toHaveText("已加入");

  await words.nth(1).click();
  await expect(page.locator("#wordTitle")).toHaveText("world");
  await expect(page.locator("#addVocab")).toHaveText("加入生词本");
  await expect(page.locator("#addVocab")).toBeEnabled();

  await page.keyboard.press("Alt+T");
  await expect(page.locator("#translation")).toBeVisible();
  await expect(page.locator("#translation")).toContainText("你好，世界。");

  await page.keyboard.press("Alt+T");
  await expect(page.locator("#translation")).toBeHidden();

  await page.keyboard.press("Alt+T");
  await expect(page.locator("#translation")).toBeVisible();

  await page.keyboard.press("Alt+A");
  await expect(page.locator("#addVocab")).toHaveText("已加入");

  await page.keyboard.press("Escape");
  await expect(page.locator("#wordCard")).toBeHidden();
  await expect(page.locator("#translation")).toBeHidden();
});

test("sentence analysis unlocks after correct dictation", async ({ page }) => {
  await mockYouTube(page);
  await page.route("**/api/transcript?*", async route => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true, video_id: "analysis1", video_title: "Analysis",
        language: "English", language_code: "en", is_generated: false,
        segmentation_version: "e2e-v1",
        items: [{text: "I can run the program.", start: 0, end: 2, duration: 2}]
      })
    });
  });
  let calls = 0;
  await page.route("**/api/sentence-analysis", async route => {
    calls += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true, analysis: "【句意】我能运行程序。\\n【句子结构】主谓宾\\n【易混词义】run：运行，不是奔跑",
        model: "e2e", cached: false
      })
    });
  });

  await page.goto("/");
  await page.locator("#url").fill("https://youtu.be/analysis1");
  await page.getByRole("button", { name: "获取字幕并开始" }).click();
  await expect(page.locator("#analyzeSentence")).toBeDisabled();
  await page.locator("#answer").fill("I can run the program");
  await page.locator("#answer").press("Enter");
  await expect(page.locator("#feedback")).toContainText("全部正确");
  await expect(page.locator("#analyzeSentence")).toBeEnabled();
  await page.locator("#analyzeSentence").click();
  await expect(page.locator("#sentenceAnalysis")).toContainText("run：运行，不是奔跑");
  await page.locator("#analyzeSentence").click();
  expect(calls).toBe(1);
});

test("new household pages load", async ({ page }) => {
  await mockYouTube(page);

  await page.goto("/library");
  await expect(page.getByRole("heading", { name: "媒体库" })).toBeVisible();

  await page.goto("/resources");
  await expect(page.getByRole("heading", { name: "学习资源库" })).toBeVisible();

  await page.goto("/assessment");
  await expect(page.getByRole("heading", { name: "听力水平评估" })).toBeVisible();
  await expect(page.getByRole("button", { name: "开始 12 题评估" })).toBeVisible();

  await page.goto("/review");
  await expect(page.getByRole("heading", { name: /错句/ })).toBeVisible();
});
