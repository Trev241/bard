const router = require("express").Router();
const path = require("path");
const { uint8arrayToString } = require("./utils");
// const { Worker } = require("worker_threads");
// const { python } = require("pythonia");
const spawn = require("child_process").spawn;

require("dotenv").config();

let botStatus = false;
const botScript = "./../bot/main.py";
const pythonExe = "./../bot/venv/bin/python3";

// const botScript = "./bot/main.py";
// const pythonExe = "./bot/venv/scripts/python";

router
  .route("/")
  .get((req, res) =>
    res.sendFile(path.join(__dirname + "public", "index.html"))
  );

router.route("/status").get((req, res) => res.send({ online: botStatus }));

router.route("/set").post((req, res) => {
  if (req.body.secret === process.env.SECRET) {
    botStatus = req.body.mode;

    // if (botStatus) worker = new Worker("./bot-worker.js");
    // else python.exit();

    if (botStatus) {
      const scriptExecution = spawn(pythonExe, ["-u", botScript]);
      scriptExecution.stdout.on("data", (data) => {
        console.log(uint8arrayToString(data));
      });
    }

    res.send({ running: botStatus });
  } else res.status(403).send({ message: "Invalid secret." });
});

router.route("/notify").post((req, res) => {
  if (req.headers.secret === process.env.SECRET) {
    botStatus = req.body.running;
    res.sendStatus(200);
  } else res.status(403).send({ message: "Invalid secret." });
});

module.exports = router;
