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

test("new household pages load", async ({ page }) => {
  await mockYouTube(page);

  await page.goto("/library");
  await expect(page.getByRole("heading", { name: "媒体库" })).toBeVisible();

  await page.goto("/assessment");
  await expect(page.getByRole("heading", { name: "听力水平评估" })).toBeVisible();
  await expect(page.getByRole("button", { name: "开始 12 题评估" })).toBeVisible();

  await page.goto("/review");
  await expect(page.getByRole("heading", { name: /错句/ })).toBeVisible();
});
