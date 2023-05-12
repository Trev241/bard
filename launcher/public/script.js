let botStatus = false;
let errorText;
let form;

window.onload = async () => {
  // Handle form submission
  form = document.forms[0];
  form.addEventListener("submit", handleSubmit);

  await updateStatus();

  errorText = document.getElementById("error");
};

const updateStatus = async () => {
  // Fetch and update current status current status
  const response = await fetch("/status");
  botStatus = (await response.json()).online;

  const dot = document.getElementById("dot");
  const statusText = document.getElementById("status");
  const actionText = document.getElementById("action");
  const intentText = document.getElementById("intent");
  const submitBtn = document.getElementById("submit");

  if (botStatus) {
    dot.classList.add("animate-pulse", "bg-green-500");
    dot.classList.remove("bg-red-500", "invisible");
    submitBtn.innerHTML = "Rest";
    actionText.innerHTML = "on duty";
    statusText.innerHTML = "ONLINE";
    intentText.innerHTML = "grant him rest";

    const commandNode = document.createElement("span");
    commandNode.innerHTML = "shutdown";
    commandNode.classList.add("font-mono", "bg-gray-700", "rounded", "p-1");

    const noticeNode = document.createElement("p");
    const noticeText1 = document.createTextNode(
      "Bard is now online. Remember to give the command "
    );
    const noticeText2 = document.createTextNode(
      " when you're finished to allow Bard to rest!"
    );

    noticeNode.classList.add("max-h-full", "break-words", "mb-4");
    noticeNode.append(noticeText1, commandNode, noticeText2);

    form.parentNode.replaceChild(noticeNode, form);
  } else {
    dot.classList.remove("animate-pulse", "bg-green-500", "invisible");
    dot.classList.add("bg-red-500");
    submitBtn.innerHTML = "Awaken";
    actionText.innerHTML = "asleep";
    statusText.innerHTML = "OFFLINE";
    intentText.innerHTML = "dispel his slumber";
  }
};

const handleSubmit = async (e) => {
  e.preventDefault();

  fetch("/set", {
    headers: {
      "Content-Type": "application/json",
    },
    method: "POST",
    body: JSON.stringify({
      secret: e.target.elements["secret"].value,
      mode: !botStatus,
    }),
  })
    .then((response) => {
      if (response.status === 403)
        throw new Error("Looks like you got the charm wrong!");
      if (response.status === 500)
        throw new Error("Something has upset the universe. Try again later.");
      return response.json();
    })
    .then((responseJson) => {
      botStatus = responseJson.running;
      window.location.reload();
    })
    .catch((err) => {
      errorText.innerHTML = err.message;

      const input = document.getElementById("secret");
      input.classList.remove("shake");
      input.classList.add("border", "border-red-500");

      setTimeout(() => input.classList.add("shake"), 100);
    });
};
