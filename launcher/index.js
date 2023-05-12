const { Worker } = require("worker_threads");
const { python } = require("pythonia");
const express = require("express");
const cors = require("cors");
const path = require("path");

const runBotService = () =>
  new Promise((resolve, reject) => {
    const worker = new Worker("./bot-worker.js");

    worker.on("message", resolve);
    worker.on("error", reject);
    worker.on("exit", (code) => {
      if (code !== 0) reject(new Error(`Worker stopped ${code} exit code`));
    });
  });

let asyncio;
let bot;

(async () => {
  try {
    asyncio = await python("asyncio");
    bot = await python("./../main.py");
  } catch (err) {
    console.error(err);
  }
})();

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

app.use(require("./routes"));

const PORT = 5000;
app.listen(PORT, () => console.log(`Launcher listening on port ${PORT}`));
