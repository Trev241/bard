document.getElementById("btn-submit").addEventListener("click", () => {
  // Since we are overriding the click button, we should fire the submit event
  document.forms[0].submit();

  const sectionElmt = document.getElementById("main");
  sectionElmt.innerHTML = `
    <div>
      <h1 class="text-5xl md:text-8xl mb-4">Loading...</h1>
      <h2 class="text-xl md:text-3xl">Don't worry, this won't take too long</h2>
    </div>
  `;
});
