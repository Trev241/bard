const express = require("express");
const cors = require("cors");
const path = require("path");

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

const PORT = 5000;

// ExpressJS-only
// app.listen(PORT, () => console.log(`Launcher listening on port ${PORT}`));

// ExpressJS + Socket.io
const server = require("http").createServer(app);
const io = require("socket.io")(server);

io.on("connection", (client) => {
  console.log(`${client} connected.`);

  client.on("message", (event) => {
    console.log("Received message ", event);
  });

  client.on("disconnected", () => {
    console.log(`${client} disconnected.`);
  });
});

app.use(require("./routes")(io));

server.listen(PORT);
