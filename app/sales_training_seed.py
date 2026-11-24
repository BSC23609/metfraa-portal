"""Seed content for the Metfraa Sales Training module.

Idempotent: lessons and quiz questions are upserted by their stable `code`, so
editing the text here and redeploying refreshes the live content without
creating duplicates. Progress and quiz attempts are never touched.
"""
from .database import SessionLocal
from .models import SalesLesson, SalesQuizQuestion

# ------------------------------------------------------------------ lessons
# (code, track, track_order, sort_order, title, level, est_minutes, summary, body_html)
LESSONS = [
    # ---------------------------------------------------------- Foundations
    ("found-1", "Foundations", 1, 1,
     "Who we are: Metfraa & the Bharat Steel Group", "New hire", 6,
     "Where Metfraa sits in the group and why that backing is our biggest selling point.",
     """
<h4>Metfraa in one line</h4>
<p>Metfraa Steel Buildings Pvt. Ltd. designs, manufactures and erects
<b>pre-engineered steel buildings (PEB)</b> &mdash; factories, warehouses,
industrial sheds and other steel structures. Our tagline is
<i>&ldquo;Steeling the Future.&rdquo;</i></p>

<h4>The group behind us</h4>
<p>Metfraa is part of the <b>Bharat Steel Group</b>, a Chennai industrial house
that started in 1989 and today is a family of 200+ people across four businesses:</p>
<ul>
  <li><b>Bharat Steel Chennai (BSC)</b> &mdash; structural steel trading and
      processing (stockist + cut-to-length / slitting). An authorised distributor
      for leading mills.</li>
  <li><b>Metfraa</b> &mdash; pre-engineered buildings (us).</li>
  <li><b>Crayon Roofings &amp; Structures</b> &mdash; roofing sheets and accessories.</li>
  <li><b>Vestrics Solutions</b> &mdash; the software / AI arm.</li>
</ul>

<h4>Why this matters to a customer</h4>
<p>A PEB is mostly steel. Because our own group trades and processes structural
steel, Metfraa has <b>material security, quality control from the raw material up,
and buying strength</b> that a standalone fabricator does not. When you sell
Metfraa, you are not selling one small workshop &mdash; you are selling a
steel group that controls its supply chain. Lead with that.</p>
"""),

    ("found-2", "Foundations", 1, 2,
     "What is a Pre-Engineered Building (PEB)?", "New hire", 7,
     "The core concept every salesperson must be able to explain in 60 seconds.",
     """
<h4>The idea</h4>
<p>In a PEB, the whole building is <b>engineered, designed and fabricated in the
factory to the exact loads of the project</b>, then shipped to site as numbered
members and simply <b>bolted together</b>. Conventional construction, by contrast,
pours concrete and welds standard hot-rolled sections at site.</p>

<h4>What makes it &ldquo;pre-engineered&rdquo;</h4>
<ul>
  <li><b>Tapered built-up sections:</b> columns and rafters are built from steel
      plate and shaped to carry more steel only where the load is high &mdash; so
      no steel is wasted. This is the single biggest reason PEB is lighter and
      cheaper than conventional steel.</li>
  <li><b>Designed to the project:</b> span, height, wind, seismic and crane loads
      are fed into the design, so each building is optimised rather than
      over-built.</li>
  <li><b>Factory-made, site-assembled:</b> members arrive drilled, cut and painted;
      site work is mostly bolting, which is fast and clean.</li>
</ul>

<h4>Say it simply</h4>
<p>&ldquo;We engineer your building to its exact loads, make it in our factory,
and bolt it up at your site &mdash; so it is lighter, faster and more predictable
than conventional construction.&rdquo;</p>
"""),

    ("found-3", "Foundations", 1, 3,
     "PEB components & terminology", "New hire", 8,
     "The words you will hear on every enquiry &mdash; know them cold.",
     """
<h4>Primary framing (the skeleton)</h4>
<ul>
  <li><b>Main frame / rigid frame:</b> the tapered columns and rafters that carry
      the building.</li>
  <li><b>Bay spacing:</b> the distance between two frames along the length.</li>
  <li><b>Span / width:</b> clear distance across the building. &ldquo;Clear span&rdquo;
      means no internal columns.</li>
  <li><b>Eave height:</b> height from floor to where the wall meets the roof.</li>
  <li><b>Roof slope / pitch:</b> the fall of the roof (e.g. 1:10).</li>
</ul>

<h4>Secondary framing</h4>
<ul>
  <li><b>Purlins &amp; girts:</b> Z / C sections that span between frames and carry
      the sheeting (purlins on the roof, girts on the walls).</li>
  <li><b>Bracing:</b> rods or angles that keep the building stable against wind.</li>
</ul>

<h4>Cladding &amp; accessories</h4>
<ul>
  <li><b>Roof &amp; wall sheeting:</b> profiled steel sheets. (Our sister company
      Crayon is a roofing specialist &mdash; useful for cladding conversations.)</li>
  <li><b>Insulation, skylights, turbo ventilators, louvers, gutters, flashings,
      roll-up / sliding doors.</b></li>
  <li><b>Mezzanine:</b> an intermediate steel floor to add usable area.</li>
  <li><b>Crane system:</b> gantry / EOT crane support built into the frame.</li>
</ul>

<p>Knowing these lets you take an accurate enquiry and sound credible on the
first call.</p>
"""),

    # ---------------------------------------------------------- Product & Value
    ("prod-1", "Product & Value", 2, 1,
     "The Metfraa edge: why we win", "All levels", 7,
     "Our differentiators, in the order you should use them.",
     """
<h4>1. The steel-group advantage (our #1 USP)</h4>
<p>We are backed by a steel group that <b>trades and processes structural steel</b>.
That means material availability, control over quality from the raw steel, and
cost strength. A customer buying from Metfraa is buying from the supply chain, not
just a fabricator.</p>

<h4>2. In-house engineering</h4>
<p>Buildings are designed to the project's real loads following recognised codes
(e.g. IS 800 and MBMA practice). Optimised design means less steel for the same
strength &mdash; which protects both quality and price.</p>

<h4>3. Single-point responsibility</h4>
<p>Design, manufacture and erection under one roof. The customer has one team
accountable from drawing to handover &mdash; fewer interfaces, fewer disputes.</p>

<h4>4. Speed &amp; predictability</h4>
<p>Factory fabrication runs in parallel with site civil work, and bolted assembly
is fast. The customer gets a more predictable schedule than wet construction.</p>

<h4>5. One group for the whole envelope</h4>
<p>Structure from Metfraa, roofing from Crayon, steel from BSC &mdash; we can
support the full building envelope. Use this when a customer worries about
coordinating multiple vendors.</p>

<p><b>Rule of thumb:</b> always open on value (group strength, engineering,
responsibility, speed) <i>before</i> price. Price alone is a race to the bottom
that a small fabricator will always &ldquo;win&rdquo; on paper.</p>
"""),

    ("prod-2", "Product & Value", 2, 2,
     "PEB vs conventional construction: the business case", "All levels", 7,
     "The comparison that turns a 'maybe' into a 'yes'.",
     """
<h4>Frame the choice as a business decision, not a steel decision</h4>
<table style="border-collapse:collapse;width:100%;font-size:13px">
  <tr style="background:#0A2B66;color:#fff">
    <th style="padding:6px 8px;text-align:left;border:1px solid #0A2B66">Factor</th>
    <th style="padding:6px 8px;text-align:left;border:1px solid #0A2B66">PEB (Metfraa)</th>
    <th style="padding:6px 8px;text-align:left;border:1px solid #0A2B66">Conventional</th>
  </tr>
  <tr><td style="padding:6px 8px;border:1px solid #e2e8f0">Weight / steel used</td><td style="padding:6px 8px;border:1px solid #e2e8f0">Lighter &mdash; tapered sections</td><td style="padding:6px 8px;border:1px solid #e2e8f0">Heavier &mdash; uniform sections</td></tr>
  <tr><td style="padding:6px 8px;border:1px solid #e2e8f0">Speed</td><td style="padding:6px 8px;border:1px solid #e2e8f0">Fast &mdash; factory + bolted</td><td style="padding:6px 8px;border:1px solid #e2e8f0">Slower &mdash; site welding / curing</td></tr>
  <tr><td style="padding:6px 8px;border:1px solid #e2e8f0">Quality</td><td style="padding:6px 8px;border:1px solid #e2e8f0">Factory-controlled</td><td style="padding:6px 8px;border:1px solid #e2e8f0">Depends on site labour</td></tr>
  <tr><td style="padding:6px 8px;border:1px solid #e2e8f0">Future expansion</td><td style="padding:6px 8px;border:1px solid #e2e8f0">Easy &mdash; add bays, bolt on</td><td style="padding:6px 8px;border:1px solid #e2e8f0">Harder</td></tr>
  <tr><td style="padding:6px 8px;border:1px solid #e2e8f0">Large clear spans</td><td style="padding:6px 8px;border:1px solid #e2e8f0">A core strength</td><td style="padding:6px 8px;border:1px solid #e2e8f0">Expensive / difficult</td></tr>
</table>

<h4>Talk total cost, not just rupees per tonne</h4>
<p>A warehouse that is ready months earlier starts earning or storing months
earlier. Faster handover, lower site labour, less rework and easy future
expansion are real money. Teach the customer to compare <b>time-to-use and
lifetime cost</b>, not only the quotation figure.</p>

<h4>Where PEB is the obvious winner</h4>
<p>Wide column-free spaces, repetitive structures, tight timelines, and anything
that may need to grow later.</p>
"""),

    ("prod-3", "Product & Value", 2, 3,
     "Industries & applications", "All levels", 5,
     "Who buys PEB &mdash; so you know where to look and what to ask.",
     """
<h4>Typical applications</h4>
<ul>
  <li><b>Factories &amp; manufacturing plants</b> (often with crane / mezzanine).</li>
  <li><b>Warehouses &amp; logistics / cold-storage sheds</b> &mdash; large clear spans.</li>
  <li><b>Workshops, godowns, processing units.</b></li>
  <li><b>Showrooms, commercial halls, aircraft / bus depots.</b></li>
  <li><b>Infrastructure structures</b> &mdash; our team has national and railway
      project background, which builds trust on larger works.</li>
</ul>

<h4>Reading the customer</h4>
<p>Match the pitch to the buyer:</p>
<ul>
  <li><b>Factory owner / MSME promoter:</b> cares about cost, speed to production,
      and expansion.</li>
  <li><b>Logistics / 3PL:</b> cares about clear span, height for racking, and
      quick roll-out across sites.</li>
  <li><b>Consultant / architect / PMC:</b> cares about engineering credibility,
      drawings, and compliance &mdash; talk design and standards.</li>
  <li><b>Contractor / EPC:</b> cares about reliable delivery and single-point
      responsibility.</li>
</ul>
"""),

    # ---------------------------------------------------------- Selling Metfraa
    ("sell-1", "Selling Metfraa", 3, 1,
     "The sales process & discovery", "All levels", 7,
     "The stages of a PEB sale and the questions that qualify an enquiry.",
     """
<h4>The journey</h4>
<p>Enquiry &rarr; Discovery &rarr; Site &amp; requirement understanding &rarr;
Budgetary offer &rarr; Technical &amp; commercial discussion &rarr; Final offer
&amp; negotiation &rarr; Order &rarr; Drawings &amp; approval &rarr; Manufacture
&rarr; Erection &rarr; Handover. Your job as sales is to drive the first six
cleanly.</p>

<h4>Discovery: ask before you quote</h4>
<p>A good quotation starts with good questions. Always capture:</p>
<ul>
  <li><b>Dimensions:</b> length &times; width (span) &times; eave height; clear span
      or internal columns allowed?</li>
  <li><b>Use:</b> warehouse, factory, cold storage? Any <b>crane</b> (capacity) or
      <b>mezzanine</b>?</li>
  <li><b>Location:</b> for wind / seismic zone and transport distance.</li>
  <li><b>Cladding &amp; add-ons:</b> sheeting type, insulation, ventilation,
      skylights, doors.</li>
  <li><b>Timeline &amp; budget</b>, and <b>who decides</b>.</li>
</ul>

<h4>Qualify early</h4>
<p>Confirm it is a real project with a decision-maker, a site and a timeframe
before you invest in a detailed offer. A budgetary (ball-park) number can hold
the conversation while you qualify.</p>
"""),

    ("sell-2", "Selling Metfraa", 3, 2,
     "What drives a PEB quotation", "All levels", 6,
     "Understand the price so you can defend it and guide the customer.",
     """
<h4>The big cost drivers</h4>
<ul>
  <li><b>Steel tonnage</b> &mdash; the single biggest factor. Driven by span,
      height, loads and spacing.</li>
  <li><b>Clear span &amp; eave height</b> &mdash; wider and taller means more steel.</li>
  <li><b>Loads</b> &mdash; crane capacity, mezzanine, wind/seismic zone, extra live
      load all add steel.</li>
  <li><b>Cladding &amp; accessories</b> &mdash; sheet spec, insulation, skylights,
      ventilators, doors.</li>
  <li><b>Scope</b> &mdash; supply only, or supply + erection; site distance.</li>
  <li><b>Steel price</b> &mdash; a live commodity. Here the group's steel buying
      strength is a genuine advantage.</li>
</ul>

<h4>How to use this</h4>
<p>When a customer says &ldquo;just give me a rate,&rdquo; explain that a PEB is
engineered to the building &mdash; the smartest design uses the least steel for
the required strength, which is exactly what our in-house engineering delivers.
A slightly higher rate on a lighter, correctly-designed building can cost
<b>less in total</b> than a cheap rate on an over- or under-designed one.</p>

<p>Always confirm what a competitor's quote <i>includes</i> (design loads, sheet
thickness, accessories, erection) before comparing numbers. Cheap quotes usually
leave things out.</p>
"""),

    ("sell-3", "Selling Metfraa", 3, 3,
     "Handling objections", "Experienced", 8,
     "The objections you will actually hear, with answers that hold up.",
     """
<h4>&ldquo;The local fabricator is cheaper.&rdquo;</h4>
<p>Agree, then reframe: &ldquo;On paper, often yes. But check what's inside that
number &mdash; design to your real loads, sheet thickness, accessories, and who is
responsible if it fails. We engineer to code, back it with a steel group, and give
you one point of responsibility. That's what protects your investment.&rdquo;</p>

<h4>&ldquo;Your price is high.&rdquo;</h4>
<p>Don't drop price first &mdash; drop ambiguity. Compare like-for-like scope, show
the lighter optimised design, and talk total cost (time-to-use, rework, future
expansion). If you must move, trade: adjust scope, not just the figure.</p>

<h4>&ldquo;Steel prices keep changing / I'll wait.&rdquo;</h4>
<p>Use the group's steel position: we are closer to the material than most, and we
can advise on timing. Waiting also delays the building earning its keep.</p>

<h4>&ldquo;Delivery takes too long.&rdquo;</h4>
<p>Explain that factory work runs in parallel with site civil work, and bolted
erection is fast &mdash; usually quicker than conventional. Give a realistic, honest
schedule; a promise you keep wins the next order too.</p>

<h4>&ldquo;I've never heard of Metfraa.&rdquo;</h4>
<p>Lead with the group: Bharat Steel Group since 1989, 200+ people, steel trading
and processing, roofing, and PEB &mdash; and our project track record. We are not a
new workshop; we are the building arm of an established steel house.</p>

<h4>Golden rules</h4>
<ul>
  <li>Never badmouth a competitor &mdash; reframe on value.</li>
  <li>Never over-promise a date or a spec to win &mdash; it costs more later.</li>
  <li>Answer the objection, then ask a question to keep control of the call.</li>
</ul>
"""),

    ("sell-4", "Selling Metfraa", 3, 4,
     "Closing & follow-up", "Experienced", 6,
     "Turning a good offer into a signed order &mdash; and the next referral.",
     """
<h4>Ask for the order</h4>
<p>Many sales stall because no one asks. Once the offer is understood, move to a
close: &ldquo;If we align on scope and schedule, shall we start your drawings this
week?&rdquo; A soft, specific next step beats &ldquo;let me know.&rdquo;</p>

<h4>Make saying yes easy</h4>
<ul>
  <li>Summarise scope, price and timeline in writing &mdash; no surprises.</li>
  <li>Offer a clear advance / payment schedule.</li>
  <li>Share relevant reference projects and, where useful, the group's strength.</li>
  <li>Remove the last risk: single-point responsibility, engineering backing.</li>
</ul>

<h4>Follow up like a professional</h4>
<p>Most orders come after several touches. Agree the next step and date on every
call, log it, and follow up when you said you would. Persistence that is helpful,
not pushy, is what converts.</p>

<h4>After the order</h4>
<p>A delivered project is your best salesperson. Stay close through drawings,
manufacture and erection; a happy customer gives references and repeat business
&mdash; and often expansion bays later.</p>
"""),
]

# ------------------------------------------------------------------ quiz
# (code, sort, question, options[list of (id,text)], correct_id, explanation)
QUIZ = [
    ("q1", 1, "What is Metfraa's single biggest differentiator versus a standalone fabricator?",
     [("a", "It is the cheapest option in every quote"),
      ("b", "It is backed by a steel group that trades and processes structural steel"),
      ("c", "It only builds very small sheds"),
      ("d", "It imports all its steel from abroad")],
     "b", "Metfraa is part of the Bharat Steel Group, giving material security, quality control and buying strength a lone fabricator can't match."),

    ("q2", 2, "In a pre-engineered building, members mostly arrive at site and are:",
     [("a", "Cast in concrete on site"),
      ("b", "Welded together from standard sections on site"),
      ("c", "Bolted together after being fabricated in the factory"),
      ("d", "3D-printed on site")],
     "c", "PEB members are engineered and fabricated in the factory, then bolted together at site — fast and clean."),

    ("q3", 3, "Why are PEB frames lighter than conventional steel frames?",
     [("a", "They use plastic instead of steel"),
      ("b", "Tapered built-up sections put steel only where the load needs it"),
      ("c", "They are always smaller buildings"),
      ("d", "They skip the foundation")],
     "b", "Tapered sections carry more steel only where the load is high, so no steel is wasted — the core PEB economy."),

    ("q4", 4, "What does 'clear span' mean?",
     [("a", "The building has no roof"),
      ("b", "The distance across the building with no internal columns"),
      ("c", "The gap between two bolts"),
      ("d", "The colour of the sheeting")],
     "b", "Clear span is the column-free width — a core PEB strength customers value for warehouses and factories."),

    ("q5", 5, "Purlins and girts are part of which framing?",
     [("a", "Primary framing"),
      ("b", "Secondary framing"),
      ("c", "The foundation"),
      ("d", "The crane system")],
     "b", "Purlins (roof) and girts (walls) are secondary members that span between frames and carry the sheeting."),

    ("q6", 6, "A customer says 'just give me a rate per tonne.' The best response is to:",
     [("a", "Quote the lowest possible rate immediately"),
      ("b", "Explain a PEB is engineered to the building, and smart design uses the least steel for the required strength"),
      ("c", "Refuse to talk about price"),
      ("d", "Tell them to ask a competitor")],
     "b", "Price depends on the engineered design; a lighter, correctly-designed building can cost less in total even at a higher rate."),

    ("q7", 7, "Which is the single biggest driver of a PEB's price?",
     [("a", "The colour of the paint"),
      ("b", "Steel tonnage"),
      ("c", "The number of doors"),
      ("d", "The company logo")],
     "b", "Steel tonnage — driven by span, height, loads and spacing — is the largest cost factor."),

    ("q8", 8, "Before comparing your quote to a cheaper competitor's, you should first:",
     [("a", "Drop your price to match"),
      ("b", "Check what the competitor's quote actually includes (loads, sheet thickness, accessories, erection)"),
      ("c", "Walk away from the deal"),
      ("d", "Increase your price")],
     "b", "Cheap quotes usually leave things out. Compare like-for-like scope before discussing the number."),

    ("q9", 9, "When a customer objects 'the local fabricator is cheaper,' the recommended approach is to:",
     [("a", "Say the fabricator does bad work"),
      ("b", "Agree it may look cheaper, then reframe on scope, engineering, responsibility and group backing"),
      ("c", "Immediately give the biggest discount you can"),
      ("d", "End the conversation")],
     "b", "Reframe on value, never badmouth the competitor, and show what the cheaper number leaves out."),

    ("q10", 10, "Discovery questions should be asked:",
     [("a", "After sending the final quotation"),
      ("b", "Before preparing a quotation"),
      ("c", "Only if the customer insists"),
      ("d", "Never — just quote a standard rate")],
     "b", "A good quotation starts with good questions — dimensions, use, loads, location, timeline and decision-maker."),

    ("q11", 11, "Which feature makes future expansion of a PEB easy?",
     [("a", "It must be demolished and rebuilt"),
      ("b", "Additional bays can be bolted on to the existing frame"),
      ("c", "Expansion is impossible"),
      ("d", "You pour new concrete walls")],
     "b", "PEBs can grow by adding bays — a strong selling point for customers who may scale up."),

    ("q12", 12, "The best way to talk about cost with a customer is in terms of:",
     [("a", "Rupees per tonne only"),
      ("b", "Total cost and time-to-use, including speed, rework and future expansion"),
      ("c", "The weight of the steel alone"),
      ("d", "The number of bolts")],
     "b", "Teach the customer to compare lifetime/total cost and how soon the building starts earning, not just the quote figure."),

    ("q13", 13, "A good closing move after the offer is understood is to:",
     [("a", "Wait silently for the customer to call back"),
      ("b", "Propose a clear next step, e.g. 'shall we start your drawings this week?'"),
      ("c", "Send ten follow-up messages the same day"),
      ("d", "Drop the price without being asked")],
     "b", "Ask for the order with a soft, specific next step — many sales stall simply because no one asks."),

    ("q14", 14, "Which statement about promising delivery dates is correct?",
     [("a", "Promise the earliest date to win, and worry about it later"),
      ("b", "Give a realistic, honest schedule — a promise you keep wins the next order too"),
      ("c", "Never discuss timelines"),
      ("d", "Always say it will take a year")],
     "b", "Over-promising costs more later; an honest schedule you keep builds trust and repeat business."),
]


def seed_sales_training():
    """Upsert lessons and quiz questions by code. Idempotent; never touches
    user progress or quiz attempts."""
    db = SessionLocal()
    changes = 0
    try:
        for (code, track, t_order, s_order, title, level, mins, summary, body) in LESSONS:
            row = db.query(SalesLesson).filter(SalesLesson.code == code).first()
            if not row:
                db.add(SalesLesson(code=code, track=track, track_order=t_order,
                                   sort_order=s_order, title=title, level=level,
                                   est_minutes=mins, summary=summary, body=body,
                                   active=True))
                changes += 1
            else:
                row.track, row.track_order, row.sort_order = track, t_order, s_order
                row.title, row.level, row.est_minutes = title, level, mins
                row.summary, row.body, row.active = summary, body, True
        for (code, s_order, question, options, correct, expl) in QUIZ:
            opts = [{"id": oid, "text": txt} for (oid, txt) in options]
            row = db.query(SalesQuizQuestion).filter(SalesQuizQuestion.code == code).first()
            if not row:
                db.add(SalesQuizQuestion(code=code, sort_order=s_order, question=question,
                                         options=opts, correct_id=correct,
                                         explanation=expl, active=True))
                changes += 1
            else:
                row.sort_order, row.question, row.options = s_order, question, opts
                row.correct_id, row.explanation, row.active = correct, expl, True
        db.commit()
    finally:
        db.close()
    return changes
