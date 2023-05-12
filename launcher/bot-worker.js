const { parentPort } = require("worker_threads");

const { python } = require("pythonia");
let asyncio;
let bot;

(async () => {
  try {
    asyncio = await python("asyncio");
    bot = await python("./../bot/main.py");

    await bot.launch();
  } catch (err) {
    console.error(err);
  }
})();
