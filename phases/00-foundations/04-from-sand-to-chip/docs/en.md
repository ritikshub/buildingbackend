# From Sand to Chip: How Processors Are Made

> The chip running this page started as sand. Turning sand into a processor with billions of switches is the most precise manufacturing humanity does — which is exactly why good chips cost a fortune.

**Type:** Learn
**Languages:** —
**Prerequisites:** [Transistors & Logic Gates](../03-transistors-and-logic-gates/)
**Time:** ~40 minutes

## The Problem

Last lesson: a processor is billions of transistors. That raises an obvious question —
**how on earth do you build billions of microscopic switches** on a sliver the size of a
fingernail? And why does a cutting-edge chip cost hundreds of millions to design, in a
factory that costs tens of billions? Understanding this explains a lot about why hardware
is priced the way it is (the theme of lesson 8).

## The Concept

### Silicon: sand you can turn into switches

Chips are made from **silicon**, which comes from ordinary **sand** (silicon dioxide).
Silicon is a **semiconductor** — it conducts electricity *sometimes*, depending on how
it's treated. That "sometimes" is the whole point: it's exactly what you need to build a
switch. By adding tiny amounts of other elements (**doping**), engineers tune silicon to
conduct or not, forming transistors.

### The pipeline: sand → wafer → chip

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 490" width="100%" style="max-width:880px" role="img" aria-label="Six stages turn sand into a chip, drawn left to right as one continuous process. Stage one is sand, silicon dioxide, drawn as a mound of scattered grains; the raw material is nearly free. Stage two is purified silicon, drawn as a clean solid block, purified to fewer than one foreign atom in a billion, and doping tunes it. Stage three is the ingot, drawn as a cylinder, one large single crystal grown from that silicon. Stage four slices the ingot into thin round wafers, drawn as a lying cylinder with thin discs coming off its end like cutting a salami. Stage five prints the transistor patterns onto the wafer, drawn as light shining through a patterned mask down onto a disc that now carries a grid of dies; this is photolithography, which prints billions of transistors all at once rather than placing them one by one, and it repeats layer upon layer, dozens of layers deep. Stage six dices the finished wafer into dozens or hundreds of individual chips, called dies, drawn as the grid separated into loose squares, one of them coloured red because a single speck of dust ruined it. Beneath the strip a note explains that the features are a few nanometers wide, smaller than a virus and thinner than the wavelength of visible light, which is why cutting-edge fabs use EUV, extreme ultraviolet light, and that a name like three nanometer process is a marketing label for a manufacturing generation rather than a literal measurement. A cost band lists what you actually pay for: a fab, or fabrication plant, costs ten to twenty billion dollars; one EUV lithography machine costs a hundred and fifty million dollars or more and only one company makes them; designing a leading-edge chip costs hundreds of millions before a single one is sold; and yield, the fraction of dies that come out good, drives cost enormously. The takeaway is that the price of a high-end processor is not the sand, it is the precision, research and low yield behind each working die.">
  <defs>
    <marker id="p0l04a-arp" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
    <marker id="p0l04a-arl" markerWidth="7" markerHeight="7" refX="4.6" refY="2.5" orient="auto"><path d="M0,0 L5,2.5 L0,5 Z" fill="#7c5cff"/></marker>
    <clipPath id="p0l04a-wclip"><ellipse cx="667" cy="148" rx="32" ry="20"/></clipPath>
  </defs>

  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Sand becomes a chip in six steps — and what you pay for is precision, not the sand</text>
  <text x="450" y="45" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.8">Silicon is a semiconductor: it conducts only sometimes, which is exactly what a switch needs — doping tunes it.</text>

  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="16" y="56" width="134" height="180" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="162" y="56" width="134" height="180" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
      <rect x="308" y="56" width="134" height="180" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
      <rect x="454" y="56" width="134" height="180" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
      <rect x="600" y="56" width="134" height="180" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
      <rect x="746" y="56" width="134" height="180" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
    </g>

    <g fill="none" stroke="currentColor" stroke-opacity="0.4" stroke-width="1">
      <circle cx="83" cy="72" r="8"/><circle cx="229" cy="72" r="8"/><circle cx="375" cy="72" r="8"/>
      <circle cx="521" cy="72" r="8"/><circle cx="667" cy="72" r="8"/><circle cx="813" cy="72" r="8"/>
    </g>
    <g text-anchor="middle" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7">
      <text x="83" y="75">1</text><text x="229" y="75">2</text><text x="375" y="75">3</text>
      <text x="521" y="75">4</text><text x="667" y="75">5</text><text x="813" y="75">6</text>
    </g>

    <g text-anchor="middle" font-size="10" font-weight="700">
      <text x="83" y="92" fill="#7f7f7f">SAND</text>
      <text x="229" y="92" fill="#7c5cff">PURIFIED</text>
      <text x="375" y="92" fill="#7c5cff">INGOT</text>
      <text x="521" y="92" fill="#7c5cff">WAFERS</text>
      <text x="667" y="92" fill="#7c5cff">PATTERNED</text>
      <text x="813" y="92" fill="#7c5cff">CHIPS (DIES)</text>
    </g>
    <g text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">
      <text x="83" y="104">silicon dioxide</text>
      <text x="229" y="104">SILICON</text>
      <text x="375" y="104">single crystal</text>
      <text x="521" y="104">sliced thin, round</text>
      <text x="667" y="104">layer upon layer</text>
      <text x="813" y="104">diced apart</text>
    </g>

    <g fill="#7f7f7f" fill-opacity="0.55">
      <circle cx="55" cy="160" r="3"/><circle cx="63" cy="164" r="2.5"/><circle cx="72" cy="158" r="3.5"/>
      <circle cx="80" cy="163" r="2"/><circle cx="89" cy="159" r="3"/><circle cx="97" cy="163" r="2.5"/>
      <circle cx="105" cy="157" r="3"/><circle cx="112" cy="162" r="2"/>
      <circle cx="60" cy="150" r="2.5"/><circle cx="69" cy="146" r="3"/><circle cx="78" cy="151" r="2"/>
      <circle cx="87" cy="147" r="2.5"/><circle cx="96" cy="150" r="3"/><circle cx="104" cy="145" r="2"/>
      <circle cx="66" cy="136" r="2.5"/><circle cx="75" cy="132" r="3"/><circle cx="84" cy="137" r="2"/>
      <circle cx="93" cy="133" r="2.5"/><circle cx="101" cy="138" r="2"/>
      <circle cx="72" cy="124" r="2.5"/><circle cx="81" cy="120" r="2"/><circle cx="90" cy="124" r="3"/>
    </g>

    <g stroke="#7c5cff" stroke-width="1.5" stroke-linejoin="round">
      <path d="M198 132 L248 132 L248 166 L198 166 Z" fill="#7c5cff" fill-opacity="0.16"/>
      <path d="M198 132 L210 120 L260 120 L248 132 Z" fill="#7c5cff" fill-opacity="0.10"/>
      <path d="M248 132 L260 120 L260 154 L248 166 Z" fill="#7c5cff" fill-opacity="0.24"/>
    </g>

    <g stroke="#7c5cff" stroke-width="1.5" stroke-linejoin="round">
      <path d="M349 124 L349 162 A26 8 0 0 0 401 162 L401 124 Z" fill="#7c5cff" fill-opacity="0.16"/>
      <ellipse cx="375" cy="124" rx="26" ry="8" fill="#7c5cff" fill-opacity="0.28"/>
    </g>

    <g stroke="#7c5cff" stroke-width="1.4" stroke-linejoin="round">
      <path d="M466 126 L508 126 A6 16 0 0 1 508 158 L466 158 A6 16 0 0 1 466 126 Z" fill="#7c5cff" fill-opacity="0.16"/>
      <ellipse cx="508" cy="142" rx="6" ry="16" fill="#7c5cff" fill-opacity="0.28"/>
      <ellipse cx="521" cy="142" rx="3" ry="16" fill="#7c5cff" fill-opacity="0.28"/>
      <ellipse cx="530" cy="142" rx="3" ry="16" fill="#7c5cff" fill-opacity="0.28"/>
      <ellipse cx="558" cy="142" rx="20" ry="13" fill="#7c5cff" fill-opacity="0.20"/>
    </g>

    <g stroke="#7c5cff" stroke-width="1.4" stroke-linejoin="round">
      <rect x="637" y="112" width="60" height="5" fill="#7c5cff" fill-opacity="0.30"/>
      <ellipse cx="667" cy="148" rx="32" ry="20" fill="#7c5cff" fill-opacity="0.14"/>
    </g>
    <g fill="none" stroke="#7c5cff" stroke-width="1.2" stroke-opacity="0.9">
      <path d="M649 119 L649 126" marker-end="url(#p0l04a-arl)"/>
      <path d="M667 119 L667 126" marker-end="url(#p0l04a-arl)"/>
      <path d="M685 119 L685 126" marker-end="url(#p0l04a-arl)"/>
    </g>
    <g clip-path="url(#p0l04a-wclip)" stroke="#7c5cff" stroke-width="0.9" stroke-opacity="0.75">
      <path d="M643 128 L643 168"/><path d="M651 128 L651 168"/><path d="M659 128 L659 168"/>
      <path d="M667 128 L667 168"/><path d="M675 128 L675 168"/><path d="M683 128 L683 168"/><path d="M691 128 L691 168"/>
      <path d="M635 134 L699 134"/><path d="M635 141 L699 141"/><path d="M635 148 L699 148"/>
      <path d="M635 155 L699 155"/><path d="M635 162 L699 162"/>
    </g>

    <g stroke="#7c5cff" stroke-width="1.3" fill="#7c5cff" fill-opacity="0.20">
      <rect x="766" y="113" width="20" height="15" rx="2"/><rect x="791" y="113" width="20" height="15" rx="2"/>
      <rect x="816" y="113" width="20" height="15" rx="2"/><rect x="841" y="113" width="20" height="15" rx="2"/>
      <rect x="766" y="133" width="20" height="15" rx="2"/><rect x="791" y="133" width="20" height="15" rx="2"/>
      <rect x="841" y="133" width="20" height="15" rx="2"/>
      <rect x="766" y="153" width="20" height="15" rx="2"/><rect x="791" y="153" width="20" height="15" rx="2"/>
      <rect x="816" y="153" width="20" height="15" rx="2"/><rect x="841" y="153" width="20" height="15" rx="2"/>
    </g>
    <g stroke="#d64545" stroke-width="1.3" fill="#d64545" fill-opacity="0.16">
      <rect x="816" y="133" width="20" height="15" rx="2"/>
    </g>
    <circle cx="826" cy="140" r="2" fill="#d64545"/>

    <g text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.9">
      <text x="83" y="184">ordinary sand:</text>
      <text x="83" y="194">the raw material is</text>
      <text x="83" y="204">nearly free</text>

      <text x="229" y="184">purified to fewer than</text>
      <text x="229" y="194">ONE foreign atom</text>
      <text x="229" y="204">in a BILLION</text>

      <text x="375" y="184">grown into one large</text>
      <text x="375" y="194">crystal cylinder —</text>
      <text x="375" y="204">the ingot</text>

      <text x="521" y="184">sliced into thin round</text>
      <text x="521" y="194">wafers — like cutting</text>
      <text x="521" y="204">a salami</text>

      <text x="667" y="184">photolithography:</text>
      <text x="667" y="194">light through a mask</text>
      <text x="667" y="204">prints ALL at once</text>

      <text x="813" y="184">diced into dozens or</text>
      <text x="813" y="194">hundreds of chips</text>
      <text x="813" y="204">(dies) per wafer</text>
    </g>

    <g text-anchor="middle" font-size="8" font-weight="700">
      <text x="83" y="221" fill="#7f7f7f">the cheap part</text>
      <text x="229" y="221" fill="#7c5cff">doping tunes it</text>
      <text x="375" y="221" fill="#7c5cff">one continuous crystal</text>
      <text x="521" y="221" fill="#7c5cff">many chips per wafer</text>
      <text x="667" y="221" fill="#7c5cff">dozens of layers</text>
      <text x="813" y="221" fill="#e0930f">one flaw = a dead die</text>
    </g>

    <text x="450" y="250" text-anchor="middle" font-size="8.5" font-weight="700" fill="#7c5cff">one material, one continuous process — each step adds precision, never material</text>
    <g fill="none" stroke="#7c5cff" stroke-width="1.7">
      <path d="M20 256 L874 256" marker-end="url(#p0l04a-arp)"/>
    </g>

    <rect x="16" y="268" width="868" height="60" rx="10" fill="#7c5cff" fill-opacity="0.06" stroke="#7c5cff" stroke-opacity="0.55" stroke-width="1.4"/>
    <text x="450" y="288" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">Why step 5 is the hard one: the features are a few NANOMETERS wide — smaller than a virus, thinner than the wavelength of visible light.</text>
    <text x="450" y="303" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">So cutting-edge fabs print with EUV (extreme ultraviolet) light, and a modern chip stacks dozens of such layers with nanometer precision.</text>
    <text x="450" y="319" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.72">"3nm process" is a marketing label for a manufacturing generation, not a measurement — the printed features are larger than 3 nm.</text>

    <text x="450" y="350" text-anchor="middle" font-size="10.5" font-weight="700" fill="#e0930f">What you are actually paying for — none of it is the sand</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.6">
      <rect x="16" y="360" width="208" height="78" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
      <rect x="236" y="360" width="208" height="78" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
      <rect x="456" y="360" width="208" height="78" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
      <rect x="676" y="360" width="208" height="78" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
    </g>
    <g text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">
      <text x="120" y="380">FAB (fabrication plant)</text>
      <text x="340" y="380">EUV LITHOGRAPHY MACHINE</text>
      <text x="560" y="380">DESIGNING one chip</text>
      <text x="780" y="380">YIELD</text>
    </g>
    <g text-anchor="middle" font-size="12.5" font-weight="700" fill="#e0930f">
      <text x="120" y="402">$10–20 billion</text>
      <text x="340" y="402">$150+ million</text>
      <text x="560" y="402">hundreds of millions</text>
      <text x="780" y="402">1 speck of dust</text>
    </g>
    <g text-anchor="middle" font-size="8" fill="currentColor" opacity="0.88">
      <text x="120" y="418">to build one modern</text>
      <text x="120" y="430">chip factory</text>
      <text x="340" y="418">each — EUV = extreme ultraviolet</text>
      <text x="340" y="430">and only ONE company makes them</text>
      <text x="560" y="418">spent on a leading-edge design</text>
      <text x="560" y="430">before a single one is sold</text>
      <text x="780" y="418">ruins a die; the fraction that</text>
      <text x="780" y="430">come out good drives cost enormously</text>
    </g>
  </g>

  <text x="450" y="460" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The price of a high-end CPU is not the sand — it is the precision, research and low yield behind each working die.</text>
  <text x="450" y="479" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.75">Only a handful of companies on Earth can manufacture at the cutting edge (TSMC, Samsung, Intel).</text>
</svg>
```

1. **Purify** the silicon to astonishing purity (fewer than one foreign atom in a billion).
2. **Grow** it into a single large crystal cylinder called an **ingot**.
3. **Slice** the ingot into thin, round **wafers** (like cutting a salami).
4. **Print** the transistor patterns onto the wafer — this is the hard part (below).
5. **Dice** the finished wafer into dozens or hundreds of individual **chips** (dies).

### Photolithography: printing with light

The transistors aren't placed one by one — there are billions. Instead they're **printed
all at once** using **photolithography**: light is shone through a patterned mask onto a
light-sensitive coating on the wafer, etching the pattern. This repeats **layer upon
layer** (a modern chip has dozens of layers stacked with nanometer precision).

The features are unimaginably small — a few **nanometers** wide, smaller than a virus,
thinner than the wavelength of visible light (which is why cutting-edge fabs use
**extreme ultraviolet**, EUV, light). When you hear "3nm process," treat that number as a
**marketing label** for a manufacturing generation, not a literal measurement — the actual
printed features are larger than 3 nm.

### Yield, and why chips are so expensive

Not every chip on a wafer works — a single speck of dust or a tiny flaw ruins a die. The
fraction that come out good is the **yield**, and it drives cost enormously. Put together:

- A modern **fab** (fabrication plant) costs **$10–20 billion** to build.
- A single **EUV lithography machine** costs **$150+ million**, and only one company makes
  them.
- **Designing** a leading-edge chip costs **hundreds of millions** before a single one is
  sold.
- Only a **handful of companies** on Earth can manufacture at the cutting edge (TSMC,
  Samsung, Intel).

So the price of a high-end CPU or GPU isn't the sand — it's the fifty billion dollars of
precision, research, and low yield behind each working die.

### Moore's Law: why it kept getting better (and is slowing)

For decades, the number of transistors on a chip **roughly doubled every ~2 years** — an
observation called **Moore's Law**. That doubling is *why* computers got dramatically
faster and cheaper year after year: more transistors in the same space means more
computing for your money. Lately the doubling has slowed, because features are approaching
the size of individual atoms and the physics (and cost) get brutal — which is part of why
progress increasingly comes from *design* (more cores, specialized chips like GPUs) rather
than just smaller transistors.

## Think about it

1. Why is a semiconductor like silicon — rather than a metal (always conducts) or plastic
   (never conducts) — the right material for a switch?
2. Two chips are physically identical in size, but one has far more transistors. What did
   the manufacturer most likely change?
3. The raw sand is nearly free. So what are you actually paying for in a $1,000 processor?

## Key takeaways

- Chips are **silicon** (from sand), a **semiconductor** whose conductivity is tuned by
  **doping** to form transistors.
- Manufacturing: purify → grow an **ingot** → slice into **wafers** → **photolithography**
  prints transistor patterns layer by layer → **dice** into chips.
- Features are a few **nanometers** wide, printed with **EUV** light — the most precise
  manufacturing there is.
- Chips are expensive because of **fabs ($10–20B), EUV machines ($150M+), design costs, and
  yield** — not the raw materials.
- **Moore's Law** (transistor counts doubling ~every 2 years) drove decades of speedups and
  is now slowing as features near atomic scale.

Next: [The CPU](../05-the-cpu/) — how those transistors are arranged into the chip that runs
your programs.
