const router = require("express").Router();
const path = require("path");
const { Worker } = require("worker_threads");
const { python } = require("pythonia");

require("dotenv").config();

let botStatus = false;
let worker;

router
  .route("/")
  .get((req, res) =>
    res.sendFile(path.join(__dirname + "public", "index.html"))
  );

router.route("/status").get((req, res) => res.send({ online: botStatus }));

router.route("/set").post((req, res) => {
  if (req.body.secret === process.env.SECRET) {
    botStatus = req.body.mode;

    if (botStatus) worker = new Worker("./bot-worker.js");
    else python.exit();

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
