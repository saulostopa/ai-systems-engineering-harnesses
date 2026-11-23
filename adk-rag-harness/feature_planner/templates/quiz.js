const get = id => document.getElementById(id);
const spec = JSON.parse(get("quiz-data").textContent);
const questions = spec.questions.map((question, id) => ({...question, id}));
const levels = [["Básico","Basic"], ["Intermediário","Intermediate"], ["Avançado","Advanced"], ["Casos-limite","Edge cases"]];
const categories = {technical: ["Técnica", "Technical"], business: ["Negócio", "Business"]};
let language = "pt";
let submission = null;
let reviewAttempt = null;
const languageButton = get("language");
const quizForm = get("quiz-form");
const reviewForm = get("review-form");
const staticTexts = [...document.querySelectorAll("[data-en]")].map(node => [node, node.textContent]);

function label(pt, en) { return language === "pt" ? pt : en; }
function pair(values) { return label(...values); }
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function answers(form) {
  return new Map([...new FormData(form)].map(([id, option]) => [Number(id), Number(option)]));
}
function textFor(value) { return value[language]; }

function questionMarkup(question, accepted, graded) {
  const item = element("fieldset", "", "quiz-question");
  item.append(element("legend", pair(categories[question.category]), "quiz-topic"));
  const stem = element("p", textFor(question.stem), "quiz-stem");
  stem.id = "question-" + question.id;
  item.setAttribute("aria-describedby", stem.id);
  item.append(stem);
  question.options.forEach((choice, index) => {
    const option = element("label", "", "quiz-opt");
    const input = element("input");
    input.type = "radio";
    input.name = question.id;
    input.value = index;
    input.required = true;
    input.disabled = graded;
    input.checked = accepted.get(question.id) === index;
    option.append(input, element("span", textFor(choice)));
    if (graded && index === question.correct) option.classList.add("is-correct");
    if (graded && input.checked && index !== question.correct) option.classList.add("is-wrong");
    item.append(option);
  });
  if (graded) {
    const verdict = accepted.get(question.id) === question.correct ? label("Correta. ", "Correct. ") : label("Incorreta. ", "Incorrect. ");
    item.append(element("p", verdict + textFor(question.why) + " " + label("Fonte", "Source") + " · " + question.source, "quiz-why"));
  }
  return item;
}

function render(choices = new Map(), reviewChoices = new Map()) {
  document.documentElement.lang = label("pt-BR", "en");
  document.title = textFor(spec.title);
  get("quiz-title").textContent = document.title;
  for (const [node, portuguese] of staticTexts) node.textContent = label(portuguese, node.dataset.en);
  languageButton.textContent = label("EN", "PT");
  languageButton.setAttribute("aria-label", label("Switch to English", "Mudar para português"));
  const groups = levels.map((name, i) => {
    const section = element("section", "", "panel quiz-level");
    section.id = "tier-" + (i + 1);
    section.dataset.level = section.id;
    section.append(element("h2", pair(name)));
    questions.filter(question => question.level === i + 1).forEach(question => {
      section.append(questionMarkup(question, submission || choices, Boolean(submission)));
    });
    return section;
  });
  get("quiz-levels").replaceChildren(...groups);
  get("quiz-level-links").replaceChildren(...groups.map((group, i) => {
    const link = element("a", pair(levels[i]));
    link.href = "#" + group.id;
    return link;
  }));
  const done = (submission || choices).size;
  get("quiz-progress").value = done;
  get("quiz-progress-label").textContent = done + " / 12 " + label("respondidas", "answered");
  const submit = get("submit-quiz");
  submit.hidden = Boolean(submission);
  submit.disabled = done !== questions.length;
  get("quiz-instructions").hidden = submit.hidden;
  if (submission) renderResult(reviewChoices);
}

function renderResult(reviewChoices) {
  const score = group => group.filter(question => submission.get(question.id) === question.correct).length + " / " + group.length;
  const wrong = questions.filter(question => submission.get(question.id) !== question.correct);
  const result = get("quiz-result");
  const scores = element("ul");
  levels.forEach((name, i) => scores.append(element("li", pair(name) + " · " + score(questions.filter(q => q.level === i + 1)))));
  for (const [category, name] of Object.entries(categories)) scores.append(element("li", pair(name) + " · " + score(questions.filter(q => q.category === category))));
  result.replaceChildren(element("h2", label("Nota", "Score") + " · " + score(questions)), scores);
  result.hidden = false;

  get("review-root").hidden = !wrong.length;
  get("review-items").replaceChildren(...wrong.map(question => {
    const item = questionMarkup(question, reviewAttempt || reviewChoices, Boolean(reviewAttempt));
    const stem = item.querySelector(".quiz-stem");
    stem.id = "review-" + question.id;
    item.setAttribute("aria-describedby", stem.id);
    return item;
  }));
  if (reviewAttempt) {
    const corrected = wrong.filter(question => reviewAttempt.get(question.id) === question.correct).length;
    get("review-result").textContent = label("Acertos na revisão", "Review score") + " · " + corrected + " / " + wrong.length;
    reviewForm.querySelector("button").hidden = true;
  }
}

quizForm.addEventListener("change", () => {
  const count = answers(quizForm).size;
  get("quiz-progress").value = count;
  get("quiz-progress-label").textContent = count + " / 12 " + label("respondidas", "answered");
  get("submit-quiz").disabled = count !== questions.length;
});
quizForm.addEventListener("submit", event => {
  event.preventDefault();
  if (submission) return;
  const selected = answers(quizForm);
  if (selected.size !== questions.length) return;
  submission = selected;
  render();
  get("quiz-result").scrollIntoView({block:"nearest"});
});
reviewForm.addEventListener("submit", event => {
  event.preventDefault();
  if (reviewAttempt) return;
  const selected = answers(reviewForm);
  if (selected.size !== get("review-items").children.length) return;
  reviewAttempt = selected;
  renderResult();
});
languageButton.addEventListener("click", () => {
  const choices = answers(quizForm);
  const reviewChoices = answers(reviewForm);
  language = label("en", "pt");
  render(choices, reviewChoices);
});
get("quiz-root").hidden = false;
render();
