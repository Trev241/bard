const socket = io("https://bard-4fg4.onrender.com");
// const socket = io("http://localhost:5000");

let logContainer;

const FORMATTING_OPTIONS = {
  BOT_STDERR: ["text-red-500"],
  SERVER_MSG: ["font-bold", "pb-2"],
};

window.onload = () => {
  logContainer = document.getElementById("logContainer");
};

const log = (message, formatOpts) => {
  const line = document.createElement("li");
  line.append(`${new Date().toISOString()}: ${message}`);
  if (formatOpts) line.classList.add(...formatOpts);
  logContainer.append(line);
  line.scrollIntoView();
};

socket.on("connect", () => {
  log("Connection with server established.", FORMATTING_OPTIONS.SERVER_MSG);
  socket.emit("status");
});

socket.on("stdout", log);
socket.on("stderr", (data) => log(data, FORMATTING_OPTIONS.BOT_STDERR));
socket.on("status", (data) =>
  log(`Bot is ${data ? "ONLINE" : "OFFLINE"}`, FORMATTING_OPTIONS.SERVER_MSG)
);
socket.on("close", (data) => log(data, FORMATTING_OPTIONS.SERVER_MSG));

socket.on("disconnect", () => {
  log(
    "Disconnected from server. Cannot retrieve nor display logs until connection is restored.",
    FORMATTING_OPTIONS.SERVER_MSG
  );
});
