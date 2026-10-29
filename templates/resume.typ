// 简历模板：复刻 resume/Yulin_Yu__Resume.pdf 的版式。
// 数据与 resume/master.yaml 同结构；定制版只是条目更少、顺序与措辞不同。
// 用法：typst compile --root <项目根> --input data=/resume/master.yaml templates/resume.typ out.pdf

#let data = yaml(sys.inputs.at("data", default: "/resume/master.yaml"))
#let meta = data.meta

#let name-blue = rgb("#0070c0")
#let heading-blue = rgb("#365f91")
#let rule-blue = rgb("#4f81bd")
#let serif = "Times New Roman"  // 与原版的 Liberation Serif 等宽度
#let sans = "Arial"  // 与原版的 Liberation Sans 等宽度

#set document(title: meta.name + " - Resume", author: meta.name)
#set page(
  paper: "a4",
  margin: (x: 19mm, top: 16mm, bottom: 18mm),
  footer: context align(right, text(size: 8pt, fill: gray, counter(page).display())),
)
#set text(font: serif, size: 11pt, lang: "en", hyphenate: false)
#set par(justify: true, leading: 6.9pt, spacing: 12pt)
#show link: it => text(fill: name-blue, underline(it))

#let months = ("Jan.", "Feb.", "Mar.", "Apr.", "May", "Jun.", "Jul.", "Aug.", "Sep.", "Oct.", "Nov.", "Dec.")
#let fmt-date(d) = {
  let s = str(d)
  if s == "present" { "Present" } else {
    let (y, m) = s.split("-")
    months.at(int(m) - 1) + " " + y
  }
}
#let period(e) = fmt-date(e.start) + " - " + fmt-date(e.end)
#let url(s) = link("https://" + s, s)

// 间距按原版 PDF 实测的基线距离换算（pt）
#let section(title) = block(above: 17pt, below: 14.5pt,
  text(font: sans, weight: "bold", size: 15pt, fill: heading-blue, title))

#let bullets(items) = {
  set list(indent: 0.2em, body-indent: 0.7em, spacing: 12pt, marker: [•])
  for b in items {
    list.item({
      if "label" in b { strong(b.label + ":") + " " }
      b.text
    })
  }
}

// "Project details and code are on page {projects_page}." —— 页码按项目附录的实际位置填写
#let fill-page(s) = {
  if s.contains("{projects_page}") {
    let parts = s.split("{projects_page}")
    parts.at(0)
    context {
      let found = query(<projects>)
      if found.len() > 0 { str(counter(page).at(found.first().location()).first()) } else { "?" }
    }
    parts.at(1)
  } else { s }
}

#let entry(left-top, right-top, left-bottom, right-bottom) = block(above: 15pt, below: 14pt,
  grid(
    columns: (1fr, auto),
    row-gutter: 7.6pt,
    strong(left-top), align(right, right-top),
    left-bottom, align(right, right-bottom),
  ))

// ---------- 页眉 ----------
#block(below: 0pt, line(length: 100%, stroke: 0.6pt + rule-blue))
#block(above: 24pt, below: 16pt, text(font: sans, weight: "bold", size: 30pt, fill: name-blue, meta.name))
#block(below: 11.4pt, par(justify: false, meta.headline))
#block(above: 0pt, par(justify: false, leading: 7.6pt)[
  #link("mailto:" + meta.email, meta.email) | #meta.location | #meta.phone \
  #url(meta.linkedin)#if "github" in meta [ | #url(meta.github)]
])

// ---------- 正文 ----------
#if data.at("highlights", default: ()).len() > 0 {
  section("Highlights of Qualifications")
  bullets(data.highlights.map(h => (text: fill-page(h.text))))
}

#if data.at("education", default: ()).len() > 0 {
  section("Education")
  for e in data.education {
    entry(e.school, e.location, e.degree, period(e))
  }
}

#let experience = data.at("experience", default: ())
#for (sec, title) in (("professional", "Professional Experience"), ("academic", "Academic Technical Experience")) {
  let items = experience.filter(e => e.section == sec)
  if items.len() > 0 {
    section(title)
    for e in items {
      entry(e.title, period(e), e.org + " | " + e.location, [])
      bullets(e.bullets)
    }
  }
}

#if data.at("skills", default: ()).len() > 0 {
  section("Technical Skills")
  for s in data.skills {
    par(justify: false)[#strong(s.category + ":") #s.items.join(", ")]
  }
}

// ---------- 项目附录（新起一页） ----------
#let projects = data.at("projects", default: ())
#if projects.len() > 0 {
  pagebreak()
  [#metadata(none) <projects>]
  for (sec, singular, plural) in (
    ("selected", "Selected Software Project", "Selected Software Projects"),
    ("academic", "Additional Academic Project", "Additional Academic Projects"),
  ) {
    let items = projects.filter(p => p.section == sec)
    if items.len() > 0 {
      section(if items.len() == 1 { singular } else { plural })
      for p in items {
        block(above: 15pt, below: 14pt, par(justify: false, leading: 7.6pt, {
          if "subtitle" in p {
            strong(p.name + " | " + p.subtitle)
            linebreak()
            p.at("context") + " | " + period(p)
            linebreak()
            p.stack.join(", ")
            if "link" in p { linebreak(); url(p.link) }
          } else {
            strong(p.name + " | " + p.stack.join(", "))
          }
        }))
        bullets(p.bullets)
      }
    }
  }
}
