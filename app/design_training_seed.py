"""Seed content for the Metfraa Design (PEB engineering) Training module.

Idempotent: lessons and quiz questions are upserted by their stable `code`,
so editing the text here and redeploying refreshes the live content without
creating duplicates. Progress and quiz attempts are never touched.
"""
from .database import SessionLocal
from .models import DesignLesson, DesignQuizQuestion

# (code, track, track_order, sort_order, title, level, est_minutes, summary, body_html)
LESSONS = [
    # --------------------------------------------------- Design Foundations
    ("dfound-1", "Design Foundations", 1, 1,
     "The design brief: what to fix before you start", "New hire", 6,
     "A PEB design is only as good as its inputs. Lock these before touching the model.",
     """
<h4>Design starts with a complete brief</h4>
<p>Before any analysis, the designer must have a clear, agreed set of inputs.
Starting a model on assumptions is the biggest cause of rework. Always confirm:</p>
<ul>
  <li><b>Geometry:</b> length, width (span), eave height, roof slope, bay spacing,
      clear span or internal columns allowed.</li>
  <li><b>Use of the building:</b> warehouse, factory, cold store — and anything
      hung from or added to the frame.</li>
  <li><b>Loads:</b> live/imposed load, wind zone (from location), seismic zone,
      any <b>crane</b> (capacity, type) and <b>mezzanine</b>.</li>
  <li><b>Location:</b> decides wind speed and seismic zone, and affects transport.</li>
  <li><b>Cladding &amp; openings:</b> sheeting type/weight, insulation, skylights,
      ventilators, large doors.</li>
  <li><b>Foundation &amp; soil interface:</b> who designs the foundation, and the
      reactions the civil team needs from us.</li>
</ul>

<h4>Why it matters</h4>
<p>Every one of these changes the steel. A missed crane, a wrong wind zone or an
unstated mezzanine can mean a full redesign. Treat the brief as a checklist you
sign off before modelling.</p>
"""),

    ("dfound-2", "Design Foundations", 1, 2,
     "Anatomy of a PEB &amp; the load path", "New hire", 7,
     "The members, what each does, and how load travels from the roof to the ground.",
     """
<h4>Primary framing</h4>
<p>The <b>main rigid frames</b> — tapered columns and rafters built from steel
plate. They carry the building's loads down to the foundations.</p>

<h4>Secondary framing</h4>
<ul>
  <li><b>Purlins</b> (roof) and <b>girts</b> (walls): cold-formed Z / C sections
      that span between frames and support the sheeting.</li>
  <li><b>Eave struts, sag rods, base angles.</b></li>
</ul>

<h4>Bracing &amp; stability</h4>
<p>Rod / angle <b>bracing</b> in the roof and walls, plus <b>portal / wind
columns</b> where needed, resist lateral and longitudinal loads (wind, seismic)
and keep the building stable.</p>

<h4>The load path — memorise it</h4>
<p>Load flows in one direction, and every member exists to pass it along:</p>
<p style="background:#f1f5f9;padding:8px 10px;border-radius:6px"><b>Cladding / sheet
&rarr; purlin or girt &rarr; rafter / column (main frame) &rarr; base plate &amp;
anchor bolts &rarr; foundation.</b></p>
<p>Lateral loads additionally travel through bracing to the foundation. If you can
trace the load path for a given load, you understand the structure.</p>
"""),

    ("dfound-3", "Design Foundations", 1, 3,
     "Steel, sections &amp; the group advantage", "New hire", 6,
     "What we build members from — and why in-house steel helps the designer.",
     """
<h4>Built-up vs cold-formed</h4>
<ul>
  <li><b>Primary members:</b> tapered <b>built-up I-sections</b>, welded from steel
      plate (flanges + web). Tapering puts material only where bending is high.</li>
  <li><b>Secondary members:</b> <b>cold-formed Z and C</b> purlins/girts, rolled
      from coil.</li>
  <li><b>Bracing &amp; accessories:</b> rods, angles, pipes.</li>
</ul>

<h4>Steel grades</h4>
<p>Structural steel is specified by yield grade — the group works with
<b>E250, E350, E450 and E550</b> and high-strength steels. Higher grades carry
more load per kilogram, which the designer can use to cut weight where it counts.
Always design to the grade that will actually be supplied.</p>

<h4>The design-side group advantage</h4>
<p>Metfraa is backed by a steel group (BSC) that trades and processes structural
steel. For the designer that means realistic material availability, known plate
sizes and the freedom to optimise to grades we can actually source — not a
theoretical section the shop can't buy.</p>
"""),

    # --------------------------------------------------- Loads & Codes
    ("dcode-1", "Loads & Codes", 2, 1,
     "The codes that govern our design", "All levels", 7,
     "Know which standard does what — it's the language of every design check.",
     """
<h4>The core Indian codes</h4>
<ul>
  <li><b>IS 800 : 2007</b> — the general code for steel construction. It uses the
      <b>Limit State Method (LSM)</b> and sets member strength and deflection
      limits.</li>
  <li><b>IS 875</b> — loads: Part 1 dead loads, Part 2 imposed (live) loads,
      <b>Part 3 wind loads</b>, Part 4 snow, Part 5 special loads &amp;
      combinations.</li>
  <li><b>IS 1893</b> — earthquake (seismic) design.</li>
  <li><b>IS 811</b> — cold-formed light-gauge sections (purlins/girts).</li>
  <li><b>IS 456</b> — the civil team's code for RCC foundations (we hand them the
      reactions).</li>
</ul>

<h4>International references</h4>
<p>PEB practice also leans on <b>MBMA</b> (Metal Building Manufacturers
Association) guidance for low-rise metal buildings and sometimes <b>AISC</b> for
steel design. Use these as reference, but the project's governing Indian codes
take precedence unless the client specifies otherwise.</p>

<h4>Rule</h4>
<p>Always design to the codes named in the project specification, and record which
code version you used — it is the first thing a checker or consultant verifies.</p>
"""),

    ("dcode-2", "Loads & Codes", 2, 2,
     "Loads &amp; load combinations", "All levels", 8,
     "Every load type we account for, and how they combine under the Limit State Method.",
     """
<h4>Load types</h4>
<ul>
  <li><b>Dead load (DL):</b> self-weight of steel, sheeting, fixed items.</li>
  <li><b>Live / imposed load (LL):</b> roof access, maintenance, per IS 875 Part 2.</li>
  <li><b>Wind load (WL):</b> from the site wind speed (IS 875 Part 3) — often the
      governing lateral load for light PEB roofs, and it can cause <b>uplift</b>.</li>
  <li><b>Seismic load (EL):</b> per IS 1893; usually less critical than wind for
      light buildings but must be checked.</li>
  <li><b>Crane load:</b> vertical wheel loads plus lateral surge and longitudinal
      braking, for buildings with EOT / gantry cranes.</li>
  <li><b>Collateral load:</b> sustained loads from services hung off the frame —
      sprinklers, ducts, lighting, false ceilings.</li>
</ul>

<h4>Load combinations (Limit State Method, IS 800 Table 4)</h4>
<p>Members are checked for the worst of several factored combinations, for example:</p>
<ul>
  <li>1.5 (DL + LL)</li>
  <li>1.2 (DL + LL + WL)</li>
  <li>1.5 (DL + WL)</li>
  <li>0.9 DL + 1.5 WL &mdash; the critical <b>uplift / wind reversal</b> case for
      light roofs</li>
</ul>
<p>Serviceability (deflection) checks use <b>unfactored</b> loads. The design must
satisfy <b>every</b> relevant combination, not just the obvious gravity one — wind
uplift frequently sizes the anchor bolts and bracing.</p>
"""),

    ("dcode-3", "Loads & Codes", 2, 3,
     "Strength vs serviceability (deflection)", "All levels", 6,
     "Two different questions the design must answer — don't confuse them.",
     """
<h4>Two separate checks</h4>
<ul>
  <li><b>Strength (ultimate limit state):</b> will the member fail? Checked with
      <b>factored</b> loads against the member's capacity (bending, shear, axial,
      buckling, combined).</li>
  <li><b>Serviceability (deflection):</b> will the building move too much to be
      usable or to keep cladding intact? Checked with <b>service (unfactored)</b>
      loads against deflection limits.</li>
</ul>

<h4>Deflection limits</h4>
<p>IS 800 (Table 6) sets allowable deflection limits by member and cladding type —
expressed as a fraction of span or height (for example, roughly span/150 for
members with elastic cladding and tighter, e.g. span/180 or more, for brittle
cladding; lateral drift of columns is limited to a fraction of the eave height).
<b>Crane buildings have stricter limits</b> on both vertical deflection and
lateral drift. Always read the exact limit from the governing code / MBMA for the
case in hand rather than from memory.</p>

<h4>Why it matters</h4>
<p>A member can pass strength and still fail serviceability (sagging roofs, cracked
sheeting, doors that jam). A good design is the <b>lightest</b> section that passes
<i>both</i>.</p>
"""),

    # --------------------------------------------------- The Design Process
    ("dproc-1", "The Design Process", 3, 1,
     "The PEB design workflow, end to end", "All levels", 7,
     "The order of operations from brief to drawings.",
     """
<h4>The workflow</h4>
<ol>
  <li><b>Confirm the brief</b> — geometry, use, loads, location, cladding,
      foundation interface (see Design Foundations).</li>
  <li><b>Set geometry</b> — frame type (clear span / multi-span / lean-to), bay
      spacing, slope, heights.</li>
  <li><b>Establish loads</b> — DL, LL, wind, seismic, crane, collateral, and the
      load combinations.</li>
  <li><b>Model &amp; analyse</b> — build the frame (e.g. in STAAD.Pro), run the
      analysis, get member forces and support reactions.</li>
  <li><b>Design members</b> — size tapered frames and secondary members; check
      strength and deflection for every combination.</li>
  <li><b>Design connections &amp; bases</b> — end-plate bolted connections, base
      plates, anchor bolts; issue reactions to the civil team.</li>
  <li><b>Optimise</b> — trim tonnage while keeping every check satisfied.</li>
  <li><b>Detail &amp; deliver</b> — GA drawings, anchor-bolt plan, erection
      drawings and the bill of materials.</li>
</ol>

<h4>Discipline</h4>
<p>Don't jump to modelling before the brief and loads are fixed, and don't detail
before the design is checked. Each stage feeds the next; shortcuts upstream become
expensive errors downstream.</p>
"""),

    ("dproc-2", "The Design Process", 3, 2,
     "Frame analysis &amp; member design", "All levels", 8,
     "Modelling the frame and sizing tapered members correctly.",
     """
<h4>Modelling the frame</h4>
<p>The rigid frame is modelled (commonly in <b>STAAD.Pro</b>, supported by in-house
calculators) with the correct supports, member releases and all load cases. Good
modelling habits:</p>
<ul>
  <li>Model the real <b>tapered</b> geometry — a prismatic approximation misjudges
      forces and weight.</li>
  <li>Apply loads at the right nodes/members, in the right directions (wind
      pressure and suction, uplift).</li>
  <li>Check support conditions match reality (pinned vs fixed bases change
      reactions and drift).</li>
</ul>

<h4>Member design checks</h4>
<p>For each member and each load combination, verify:</p>
<ul>
  <li><b>Bending</b> capacity (including <b>lateral-torsional buckling</b> of the
      compression flange).</li>
  <li><b>Axial</b> (compression buckling / tension) and <b>shear</b>.</li>
  <li><b>Combined</b> axial + bending interaction.</li>
  <li><b>Deflection / drift</b> under service loads.</li>
</ul>

<h4>Sanity-check the output</h4>
<p>Software gives numbers, not judgement. Check reactions sum to the applied load,
look for unrealistic member sizes, and confirm the governing combination makes
physical sense. If a result surprises you, find out why before trusting it.</p>
"""),

    ("dproc-3", "The Design Process", 3, 3,
     "Connections, base plates &amp; foundations", "All levels", 7,
     "Where the steel meets other steel and the ground.",
     """
<h4>Bolted connections</h4>
<p>PEB connections are mostly <b>bolted end-plate</b> joints (at the eave / knee
and ridge), designed for the moment, shear and axial force they carry. Bolts,
end-plate thickness and welds are all checked. Bolted joints are what make site
erection fast.</p>

<h4>Base plates &amp; anchor bolts</h4>
<p>The column base plate and anchor bolts transfer the column's <b>reactions</b>
— vertical, horizontal (shear) and, for fixed bases, moment — into the foundation.
Wind <b>uplift</b> often governs anchor-bolt design, so never size bolts from the
gravity case alone.</p>

<h4>Hand-off to civil</h4>
<p>We design the steel; the civil team designs the RCC foundation (IS 456). The
critical deliverable from us is an accurate <b>reaction schedule and anchor-bolt
plan</b> — magnitudes, directions and bolt positions. An error here causes site
problems that are very costly to fix after concreting.</p>
"""),

    ("dproc-4", "The Design Process", 3, 4,
     "Optimisation: the Metfraa edge", "Experienced", 7,
     "Delivering the lightest compliant design — where engineering becomes value.",
     """
<h4>Why optimisation is the job, not an extra</h4>
<p>Steel tonnage is the biggest cost in a PEB. The best design uses the
<b>least steel that still passes every code check</b>. That is exactly the value
we sell — a lighter, correctly-engineered building, backed by a steel group.</p>

<h4>Levers to reduce tonnage</h4>
<ul>
  <li><b>Tapering</b> — shape columns and rafters to the bending diagram.</li>
  <li><b>Bay spacing</b> — tune the number of frames vs purlin spans for the
      overall minimum weight.</li>
  <li><b>Steel grade</b> — use higher grades where strength governs.</li>
  <li><b>Secondary member spacing</b> and section choice.</li>
  <li><b>Bracing layout</b> — efficient load paths for lateral loads.</li>
</ul>

<h4>The limit of optimisation</h4>
<p>Never optimise past the code. A section that is lighter but fails deflection,
buckling or an uplift combination is not a saving — it is a defect. Optimisation
means finding the minimum weight <i>inside</i> every limit, with a sensible margin.
Document the governing check for key members so a reviewer can see the design is
tight but safe.</p>
"""),

    # --------------------------------------------------- Deliverables & QA
    ("ddeliv-1", "Deliverables & QA", 4, 1,
     "Drawings, detailing &amp; BOM", "All levels", 6,
     "What leaves the design office, and the standards it must meet.",
     """
<h4>The design deliverables</h4>
<ul>
  <li><b>General Arrangement (GA) drawings</b> — the building laid out: frames,
      bays, heights, cross-sections.</li>
  <li><b>Anchor-bolt plan &amp; reaction schedule</b> — for the civil team, early.</li>
  <li><b>Fabrication / shop drawings</b> — every member detailed for the factory.</li>
  <li><b>Erection drawings</b> — numbered members and connections so the site team
      bolts the right piece in the right place.</li>
  <li><b>Bill of Materials (BOM)</b> — the complete material list and tonnage.</li>
</ul>

<h4>Detailing standards</h4>
<p>Drawings must be clear, consistent and buildable: correct member marks, bolt
sizes and grades, weld symbols, hole positions, and clash-free connections. A
drawing the shop or site misreads costs more than a slow, careful one. Follow the
office's title-block, marking and revision conventions on every sheet.</p>
"""),

    ("ddeliv-2", "Deliverables & QA", 4, 2,
     "Design QA &amp; checking", "Experienced", 7,
     "How we make sure a design is right before it is built.",
     """
<h4>Check your own work first</h4>
<ul>
  <li>Reactions sum to the total applied load (a quick, powerful sanity check).</li>
  <li>Every member passes <b>both</b> strength and serviceability, for the
      governing combination.</li>
  <li>Wind <b>uplift / reversal</b> cases are included — not just gravity.</li>
  <li>Connections and anchor bolts are designed for the forces they actually carry.</li>
  <li>The model geometry, supports and loads match the brief.</li>
</ul>

<h4>Independent review</h4>
<p>A second engineer checks the design independently — not just re-running the same
model, but questioning assumptions, load cases and governing checks. Catching an
error on paper is cheap; catching it at site is not.</p>

<h4>Common errors to watch for</h4>
<ul>
  <li>Wrong wind zone / basic wind speed for the location.</li>
  <li>Missed crane, mezzanine or collateral load.</li>
  <li>Uplift ignored, under-sizing anchor bolts and bracing.</li>
  <li>Passing strength but failing deflection / drift.</li>
  <li>Reaction schedule to civil issued late or wrong.</li>
</ul>
<p>Good QA is what lets us stand behind a light, optimised design with confidence.</p>
"""),
]

# (code, sort, question, options[list of (id,text)], correct_id, explanation)
QUIZ = [
    ("dq1", 1, "Which code is the general standard for steel construction design in India?",
     [("a", "IS 456"), ("b", "IS 800"), ("c", "IS 875 Part 3"), ("d", "IS 1893")],
     "b", "IS 800:2007 is the general code for steel construction and uses the Limit State Method."),

    ("dq2", 2, "Design method used by IS 800:2007 is:",
     [("a", "Working Stress Method only"), ("b", "Limit State Method"),
      ("c", "No method — it is only for loads"), ("d", "Allowable Stress Design")],
     "b", "IS 800:2007 is based on the Limit State Method (strength at factored loads, serviceability at service loads)."),

    ("dq3", 3, "Wind loads for design are taken from:",
     [("a", "IS 875 Part 3"), ("b", "IS 1893"), ("c", "IS 800 Table 6"), ("d", "IS 456")],
     "a", "IS 875 Part 3 gives wind loads; Part 1 is dead load and Part 2 is imposed/live load."),

    ("dq4", 4, "Earthquake (seismic) design is governed by:",
     [("a", "IS 811"), ("b", "IS 1893"), ("c", "MBMA"), ("d", "IS 875 Part 1")],
     "b", "IS 1893 covers seismic design. For light PEB roofs wind often governs, but seismic must still be checked."),

    ("dq5", 5, "Primary members (columns and rafters) of a PEB are typically:",
     [("a", "Cold-formed Z and C sections"), ("b", "Tapered built-up I-sections welded from plate"),
      ("c", "Reinforced concrete"), ("d", "Standard pipes")],
     "b", "Tapered built-up sections put steel only where bending is high — the core of PEB economy."),

    ("dq6", 6, "Purlins and girts are usually made as:",
     [("a", "Tapered built-up sections"), ("b", "Cold-formed Z / C sections"),
      ("c", "Solid round bars"), ("d", "RCC beams")],
     "b", "Purlins (roof) and girts (walls) are cold-formed light-gauge Z/C sections, covered by IS 811."),

    ("dq7", 7, "What is the correct gravity load path in a PEB?",
     [("a", "Foundation → column → purlin → sheet"),
      ("b", "Sheet → purlin → main frame (rafter/column) → base → foundation"),
      ("c", "Sheet → foundation directly"),
      ("d", "Bracing → purlin → sheet")],
     "b", "Load flows from the cladding through secondary members to the main frame, then to the base and foundation."),

    ("dq8", 8, "A deflection (serviceability) check is performed using:",
     [("a", "Factored loads"), ("b", "Service (unfactored) loads"),
      ("c", "Only wind uplift"), ("d", "No loads — it is geometric")],
     "b", "Serviceability/deflection is checked at service (unfactored) loads; strength is checked at factored loads."),

    ("dq9", 9, "Which load combination typically governs wind uplift / reversal on a light roof?",
     [("a", "1.5 (DL + LL)"), ("b", "0.9 DL + 1.5 WL"),
      ("c", "1.5 DL only"), ("d", "1.2 (DL + LL)")],
     "b", "0.9 DL + 1.5 WL is the critical uplift case — low dead load with high wind suction, which often sizes anchor bolts and bracing."),

    ("dq10", 10, "'Collateral load' refers to:",
     [("a", "The weight of the steel frame itself"),
      ("b", "Sustained loads from services hung off the frame (sprinklers, ducts, lighting)"),
      ("c", "Wind suction on the roof"),
      ("d", "The crane wheel load")],
     "b", "Collateral load is the sustained load from fixed services supported by the structure — it must be included in design."),

    ("dq11", 11, "Base plates and anchor bolts primarily:",
     [("a", "Support the roof sheeting"),
      ("b", "Transfer column reactions (vertical, shear, and moment if fixed) into the foundation"),
      ("c", "Brace the purlins"),
      ("d", "Carry the crane rail")],
     "b", "The base connection transfers column reactions to the foundation; wind uplift often governs anchor-bolt design."),

    ("dq12", 12, "The main goal of design optimisation in a PEB is to:",
     [("a", "Use the heaviest sections available for safety"),
      ("b", "Achieve the lightest design that still passes every code check"),
      ("c", "Reduce the number of drawings"),
      ("d", "Skip the deflection check to save time")],
     "b", "Optimisation means minimum steel tonnage while satisfying all strength and serviceability limits — never past the code."),

    ("dq13", 13, "A member passes the strength check but fails the deflection limit. The design is:",
     [("a", "Acceptable — strength is all that matters"),
      ("b", "Not acceptable — it must satisfy both strength and serviceability"),
      ("c", "Acceptable only for crane buildings"),
      ("d", "Acceptable if wind is ignored")],
     "b", "A compliant design must pass both. Excess deflection causes sagging, cracked cladding and jammed doors even if the member is 'strong enough'."),

    ("dq14", 14, "A quick, powerful sanity check after running a frame analysis is to confirm that:",
     [("a", "The drawing border is correct"),
      ("b", "The support reactions sum to the total applied load"),
      ("c", "The file is saved"),
      ("d", "The model has many members")],
     "b", "If reactions don't balance the applied loads, something is wrong with the model before you trust any member result."),
]


def seed_design_training():
    """Upsert lessons and quiz questions by code. Idempotent; never touches
    user progress or quiz attempts."""
    db = SessionLocal()
    changes = 0
    try:
        for (code, track, t_order, s_order, title, level, mins, summary, body) in LESSONS:
            row = db.query(DesignLesson).filter(DesignLesson.code == code).first()
            if not row:
                db.add(DesignLesson(code=code, track=track, track_order=t_order,
                                    sort_order=s_order, title=title, level=level,
                                    est_minutes=mins, summary=summary, body=body, active=True))
                changes += 1
            else:
                row.track, row.track_order, row.sort_order = track, t_order, s_order
                row.title, row.level, row.est_minutes = title, level, mins
                row.summary, row.body, row.active = summary, body, True
        for (code, s_order, question, options, correct, expl) in QUIZ:
            opts = [{"id": oid, "text": txt} for (oid, txt) in options]
            row = db.query(DesignQuizQuestion).filter(DesignQuizQuestion.code == code).first()
            if not row:
                db.add(DesignQuizQuestion(code=code, sort_order=s_order, question=question,
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
