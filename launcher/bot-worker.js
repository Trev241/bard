const { parentPort } = require("worker_threads");

const { python } = require("pythonia");
let asyncio;
let bot;

console.log("Hello from bot-worker.js!");

(async () => {
  try {
    asyncio = await python("asyncio");
    bot = await python("./../main.py");

    await bot.launch();
    console.log("Bot launch initiated");
  } catch (err) {
    console.error(err);
  }
})();
