const socket = io("https://bard-4fg4.onrender.com");

let logContainer;

window.onload = () => {
  logContainer = document.getElementById("logContainer");
};

const log = (message, formatOpts) => {
  const line = document.createElement("li");
  line.append(message);
  if (formatOpts) line.classList.add(...formatOpts);
  logContainer.append(line);
  line.scrollIntoView();
};

socket.on("connect", () => {
  log("Connection with server established.", ["font-bold", "py-2"]);
});

socket.on("stdout", log);
socket.on("stderr", log);

socket.on("disconnect", () => {
  log(
    "Disconnected from server. Cannot retrieve nor display logs until connection is restored.",
    ["font-bold", "py-2"]
  );
});
