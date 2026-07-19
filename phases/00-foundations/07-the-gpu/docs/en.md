# The GPU: Massively Parallel Compute

> A CPU has a few very fast, very clever cores. A GPU has thousands of simple ones. That one difference is why GPUs draw your games, train AI, and cost a fortune.

**Type:** Learn
**Languages:** —
**Prerequisites:** [The CPU](../05-the-cpu/)
**Time:** ~40 minutes

## The Problem

You know the CPU now. But "GPU" is everywhere — gaming, AI, video, crypto — and it's often
the most expensive part in the machine. What *is* a GPU, how is it different from a CPU,
and when does each one win? Getting this right decides whether you're paying for hardware
you don't need, or starving a workload that desperately wants it.

## The Concept

### Two philosophies: few clever cores vs. many simple ones

A **CPU** and a **GPU** are both made of the transistors and gates you've met — they just
arrange them for opposite goals:

- **CPU** — a *few* (4–16) large, powerful, general-purpose cores. Brilliant at complex,
  varied tasks done quickly, one after another. Think **a few expert chefs**, each able to
  cook any dish start to finish.
- **GPU** (Graphics Processing Unit) — *thousands* of small, simple cores. Each is weaker
  and less flexible, but they all work **at the same time** on lots of similar little
  tasks. Think **a huge line of cooks**, each doing one identical step on a different plate.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 628" width="100%" style="max-width:880px" role="img" aria-label="Two philosophies for arranging the same transistors and gates. On the left, the CPU panel: eight large rounded blocks, each labelled core and general-purpose, drawn in a two-by-four arrangement. The lesson gives the range as 4 to 16 large, powerful, general-purpose cores. The CPU optimizes for latency, meaning finish one complex task fast. It is brilliant at complex, varied tasks done quickly, one after another, and good at branchy, sequential, decision-heavy logic such as handling a single web request. The chef analogy is a few expert chefs, each able to cook any dish start to finish. On the right, the GPU panel, short for Graphics Processing Unit: the same footprint is instead filled with a dense grid of 384 tiny squares, twelve rows of thirty-two, each square roughly one eighty-fourth the area of a CPU core block. That size ratio is the whole point: big and few versus small and many. The lesson says a real GPU has thousands of these small, simple cores. Each is weaker and less flexible, but they all work at the same time on lots of similar little tasks, so the GPU optimizes for throughput, meaning finish a huge pile of similar tasks per second. It is bad at branchy, sequential, one-off logic. Its chef analogy is a huge line of cooks, each doing one identical step on a different plate. Below the panels, a band explains why: SIMD, Single Instruction Multiple Data, is the same operation applied across thousands of data items at once. Graphics is where GPUs came from, because a screen is millions of pixels and each pixel is computed the same way, independently. AI has the exact same shape, because a neural network is mostly matrix multiplication, millions of identical small multiply-and-add operations that are all independent, which is why AI training and inference happens on GPUs. The rule of thumb: lots of identical math on lots of data goes to the GPU, while varied, sequential, decision-heavy logic goes to the CPU. Most web backends run entirely on CPUs; GPUs enter for machine-learning inference, video transcoding, and large-scale data crunching.">
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Same transistors, opposite goals — a few big cores, or thousands of tiny ones</text>
  <text x="450" y="48" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.8">Both are built from the same transistors and gates — they just arrange them for opposite goals.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="2">
      <rect x="16" y="62" width="424" height="328" rx="12" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.8"/>
      <rect x="460" y="62" width="424" height="328" rx="12" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.8"/>
    </g>

    <g text-anchor="middle" fill="currentColor">
      <text x="228" y="88" font-size="13" font-weight="700" fill="#3553ff">CPU · optimizes for LATENCY</text>
      <text x="228" y="103" font-size="8" opacity="0.65">(Central Processing Unit)</text>
      <text x="228" y="122" font-size="9.5">finish ONE complex task fast</text>
      <text x="228" y="140" font-size="10" font-weight="700" fill="#3553ff">4–16 large, powerful, general-purpose cores</text>

      <text x="672" y="88" font-size="13" font-weight="700" fill="#0fa07f">GPU · optimizes for THROUGHPUT</text>
      <text x="672" y="103" font-size="8" opacity="0.65">(Graphics Processing Unit)</text>
      <text x="672" y="122" font-size="9.5">finish a HUGE PILE of similar tasks per second</text>
      <text x="672" y="140" font-size="10" font-weight="700" fill="#0fa07f">thousands of small, simple cores</text>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="36" y="150" width="84" height="64" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
      <rect x="136" y="150" width="84" height="64" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
      <rect x="236" y="150" width="84" height="64" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
      <rect x="336" y="150" width="84" height="64" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
      <rect x="36" y="230" width="84" height="64" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
      <rect x="136" y="230" width="84" height="64" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
      <rect x="236" y="230" width="84" height="64" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
      <rect x="336" y="230" width="84" height="64" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    </g>
    <g text-anchor="middle" fill="currentColor" font-family="'JetBrains Mono', ui-monospace, monospace">
      <text x="78" y="178" font-size="11.5" font-weight="700" fill="#3553ff">core</text><text x="78" y="195" font-size="6.5" opacity="0.7">general-purpose</text>
      <text x="178" y="178" font-size="11.5" font-weight="700" fill="#3553ff">core</text><text x="178" y="195" font-size="6.5" opacity="0.7">general-purpose</text>
      <text x="278" y="178" font-size="11.5" font-weight="700" fill="#3553ff">core</text><text x="278" y="195" font-size="6.5" opacity="0.7">general-purpose</text>
      <text x="378" y="178" font-size="11.5" font-weight="700" fill="#3553ff">core</text><text x="378" y="195" font-size="6.5" opacity="0.7">general-purpose</text>
      <text x="78" y="258" font-size="11.5" font-weight="700" fill="#3553ff">core</text><text x="78" y="275" font-size="6.5" opacity="0.7">general-purpose</text>
      <text x="178" y="258" font-size="11.5" font-weight="700" fill="#3553ff">core</text><text x="178" y="275" font-size="6.5" opacity="0.7">general-purpose</text>
      <text x="278" y="258" font-size="11.5" font-weight="700" fill="#3553ff">core</text><text x="278" y="275" font-size="6.5" opacity="0.7">general-purpose</text>
      <text x="378" y="258" font-size="11.5" font-weight="700" fill="#3553ff">core</text><text x="378" y="275" font-size="6.5" opacity="0.7">general-purpose</text>
    </g>

    <g fill="#0fa07f" fill-opacity="0.5" stroke="#0fa07f" stroke-opacity="0.85" stroke-width="0.6">
      <rect x="482" y="152" width="8" height="8"/><rect x="494" y="152" width="8" height="8"/><rect x="506" y="152" width="8" height="8"/><rect x="518" y="152" width="8" height="8"/><rect x="530" y="152" width="8" height="8"/><rect x="542" y="152" width="8" height="8"/><rect x="554" y="152" width="8" height="8"/><rect x="566" y="152" width="8" height="8"/><rect x="578" y="152" width="8" height="8"/><rect x="590" y="152" width="8" height="8"/><rect x="602" y="152" width="8" height="8"/><rect x="614" y="152" width="8" height="8"/><rect x="626" y="152" width="8" height="8"/><rect x="638" y="152" width="8" height="8"/><rect x="650" y="152" width="8" height="8"/><rect x="662" y="152" width="8" height="8"/><rect x="674" y="152" width="8" height="8"/><rect x="686" y="152" width="8" height="8"/><rect x="698" y="152" width="8" height="8"/><rect x="710" y="152" width="8" height="8"/><rect x="722" y="152" width="8" height="8"/><rect x="734" y="152" width="8" height="8"/><rect x="746" y="152" width="8" height="8"/><rect x="758" y="152" width="8" height="8"/><rect x="770" y="152" width="8" height="8"/><rect x="782" y="152" width="8" height="8"/><rect x="794" y="152" width="8" height="8"/><rect x="806" y="152" width="8" height="8"/><rect x="818" y="152" width="8" height="8"/><rect x="830" y="152" width="8" height="8"/><rect x="842" y="152" width="8" height="8"/><rect x="854" y="152" width="8" height="8"/>
      <rect x="482" y="164" width="8" height="8"/><rect x="494" y="164" width="8" height="8"/><rect x="506" y="164" width="8" height="8"/><rect x="518" y="164" width="8" height="8"/><rect x="530" y="164" width="8" height="8"/><rect x="542" y="164" width="8" height="8"/><rect x="554" y="164" width="8" height="8"/><rect x="566" y="164" width="8" height="8"/><rect x="578" y="164" width="8" height="8"/><rect x="590" y="164" width="8" height="8"/><rect x="602" y="164" width="8" height="8"/><rect x="614" y="164" width="8" height="8"/><rect x="626" y="164" width="8" height="8"/><rect x="638" y="164" width="8" height="8"/><rect x="650" y="164" width="8" height="8"/><rect x="662" y="164" width="8" height="8"/><rect x="674" y="164" width="8" height="8"/><rect x="686" y="164" width="8" height="8"/><rect x="698" y="164" width="8" height="8"/><rect x="710" y="164" width="8" height="8"/><rect x="722" y="164" width="8" height="8"/><rect x="734" y="164" width="8" height="8"/><rect x="746" y="164" width="8" height="8"/><rect x="758" y="164" width="8" height="8"/><rect x="770" y="164" width="8" height="8"/><rect x="782" y="164" width="8" height="8"/><rect x="794" y="164" width="8" height="8"/><rect x="806" y="164" width="8" height="8"/><rect x="818" y="164" width="8" height="8"/><rect x="830" y="164" width="8" height="8"/><rect x="842" y="164" width="8" height="8"/><rect x="854" y="164" width="8" height="8"/>
      <rect x="482" y="176" width="8" height="8"/><rect x="494" y="176" width="8" height="8"/><rect x="506" y="176" width="8" height="8"/><rect x="518" y="176" width="8" height="8"/><rect x="530" y="176" width="8" height="8"/><rect x="542" y="176" width="8" height="8"/><rect x="554" y="176" width="8" height="8"/><rect x="566" y="176" width="8" height="8"/><rect x="578" y="176" width="8" height="8"/><rect x="590" y="176" width="8" height="8"/><rect x="602" y="176" width="8" height="8"/><rect x="614" y="176" width="8" height="8"/><rect x="626" y="176" width="8" height="8"/><rect x="638" y="176" width="8" height="8"/><rect x="650" y="176" width="8" height="8"/><rect x="662" y="176" width="8" height="8"/><rect x="674" y="176" width="8" height="8"/><rect x="686" y="176" width="8" height="8"/><rect x="698" y="176" width="8" height="8"/><rect x="710" y="176" width="8" height="8"/><rect x="722" y="176" width="8" height="8"/><rect x="734" y="176" width="8" height="8"/><rect x="746" y="176" width="8" height="8"/><rect x="758" y="176" width="8" height="8"/><rect x="770" y="176" width="8" height="8"/><rect x="782" y="176" width="8" height="8"/><rect x="794" y="176" width="8" height="8"/><rect x="806" y="176" width="8" height="8"/><rect x="818" y="176" width="8" height="8"/><rect x="830" y="176" width="8" height="8"/><rect x="842" y="176" width="8" height="8"/><rect x="854" y="176" width="8" height="8"/>
      <rect x="482" y="188" width="8" height="8"/><rect x="494" y="188" width="8" height="8"/><rect x="506" y="188" width="8" height="8"/><rect x="518" y="188" width="8" height="8"/><rect x="530" y="188" width="8" height="8"/><rect x="542" y="188" width="8" height="8"/><rect x="554" y="188" width="8" height="8"/><rect x="566" y="188" width="8" height="8"/><rect x="578" y="188" width="8" height="8"/><rect x="590" y="188" width="8" height="8"/><rect x="602" y="188" width="8" height="8"/><rect x="614" y="188" width="8" height="8"/><rect x="626" y="188" width="8" height="8"/><rect x="638" y="188" width="8" height="8"/><rect x="650" y="188" width="8" height="8"/><rect x="662" y="188" width="8" height="8"/><rect x="674" y="188" width="8" height="8"/><rect x="686" y="188" width="8" height="8"/><rect x="698" y="188" width="8" height="8"/><rect x="710" y="188" width="8" height="8"/><rect x="722" y="188" width="8" height="8"/><rect x="734" y="188" width="8" height="8"/><rect x="746" y="188" width="8" height="8"/><rect x="758" y="188" width="8" height="8"/><rect x="770" y="188" width="8" height="8"/><rect x="782" y="188" width="8" height="8"/><rect x="794" y="188" width="8" height="8"/><rect x="806" y="188" width="8" height="8"/><rect x="818" y="188" width="8" height="8"/><rect x="830" y="188" width="8" height="8"/><rect x="842" y="188" width="8" height="8"/><rect x="854" y="188" width="8" height="8"/>
      <rect x="482" y="200" width="8" height="8"/><rect x="494" y="200" width="8" height="8"/><rect x="506" y="200" width="8" height="8"/><rect x="518" y="200" width="8" height="8"/><rect x="530" y="200" width="8" height="8"/><rect x="542" y="200" width="8" height="8"/><rect x="554" y="200" width="8" height="8"/><rect x="566" y="200" width="8" height="8"/><rect x="578" y="200" width="8" height="8"/><rect x="590" y="200" width="8" height="8"/><rect x="602" y="200" width="8" height="8"/><rect x="614" y="200" width="8" height="8"/><rect x="626" y="200" width="8" height="8"/><rect x="638" y="200" width="8" height="8"/><rect x="650" y="200" width="8" height="8"/><rect x="662" y="200" width="8" height="8"/><rect x="674" y="200" width="8" height="8"/><rect x="686" y="200" width="8" height="8"/><rect x="698" y="200" width="8" height="8"/><rect x="710" y="200" width="8" height="8"/><rect x="722" y="200" width="8" height="8"/><rect x="734" y="200" width="8" height="8"/><rect x="746" y="200" width="8" height="8"/><rect x="758" y="200" width="8" height="8"/><rect x="770" y="200" width="8" height="8"/><rect x="782" y="200" width="8" height="8"/><rect x="794" y="200" width="8" height="8"/><rect x="806" y="200" width="8" height="8"/><rect x="818" y="200" width="8" height="8"/><rect x="830" y="200" width="8" height="8"/><rect x="842" y="200" width="8" height="8"/><rect x="854" y="200" width="8" height="8"/>
      <rect x="482" y="212" width="8" height="8"/><rect x="494" y="212" width="8" height="8"/><rect x="506" y="212" width="8" height="8"/><rect x="518" y="212" width="8" height="8"/><rect x="530" y="212" width="8" height="8"/><rect x="542" y="212" width="8" height="8"/><rect x="554" y="212" width="8" height="8"/><rect x="566" y="212" width="8" height="8"/><rect x="578" y="212" width="8" height="8"/><rect x="590" y="212" width="8" height="8"/><rect x="602" y="212" width="8" height="8"/><rect x="614" y="212" width="8" height="8"/><rect x="626" y="212" width="8" height="8"/><rect x="638" y="212" width="8" height="8"/><rect x="650" y="212" width="8" height="8"/><rect x="662" y="212" width="8" height="8"/><rect x="674" y="212" width="8" height="8"/><rect x="686" y="212" width="8" height="8"/><rect x="698" y="212" width="8" height="8"/><rect x="710" y="212" width="8" height="8"/><rect x="722" y="212" width="8" height="8"/><rect x="734" y="212" width="8" height="8"/><rect x="746" y="212" width="8" height="8"/><rect x="758" y="212" width="8" height="8"/><rect x="770" y="212" width="8" height="8"/><rect x="782" y="212" width="8" height="8"/><rect x="794" y="212" width="8" height="8"/><rect x="806" y="212" width="8" height="8"/><rect x="818" y="212" width="8" height="8"/><rect x="830" y="212" width="8" height="8"/><rect x="842" y="212" width="8" height="8"/><rect x="854" y="212" width="8" height="8"/>
      <rect x="482" y="224" width="8" height="8"/><rect x="494" y="224" width="8" height="8"/><rect x="506" y="224" width="8" height="8"/><rect x="518" y="224" width="8" height="8"/><rect x="530" y="224" width="8" height="8"/><rect x="542" y="224" width="8" height="8"/><rect x="554" y="224" width="8" height="8"/><rect x="566" y="224" width="8" height="8"/><rect x="578" y="224" width="8" height="8"/><rect x="590" y="224" width="8" height="8"/><rect x="602" y="224" width="8" height="8"/><rect x="614" y="224" width="8" height="8"/><rect x="626" y="224" width="8" height="8"/><rect x="638" y="224" width="8" height="8"/><rect x="650" y="224" width="8" height="8"/><rect x="662" y="224" width="8" height="8"/><rect x="674" y="224" width="8" height="8"/><rect x="686" y="224" width="8" height="8"/><rect x="698" y="224" width="8" height="8"/><rect x="710" y="224" width="8" height="8"/><rect x="722" y="224" width="8" height="8"/><rect x="734" y="224" width="8" height="8"/><rect x="746" y="224" width="8" height="8"/><rect x="758" y="224" width="8" height="8"/><rect x="770" y="224" width="8" height="8"/><rect x="782" y="224" width="8" height="8"/><rect x="794" y="224" width="8" height="8"/><rect x="806" y="224" width="8" height="8"/><rect x="818" y="224" width="8" height="8"/><rect x="830" y="224" width="8" height="8"/><rect x="842" y="224" width="8" height="8"/><rect x="854" y="224" width="8" height="8"/>
      <rect x="482" y="236" width="8" height="8"/><rect x="494" y="236" width="8" height="8"/><rect x="506" y="236" width="8" height="8"/><rect x="518" y="236" width="8" height="8"/><rect x="530" y="236" width="8" height="8"/><rect x="542" y="236" width="8" height="8"/><rect x="554" y="236" width="8" height="8"/><rect x="566" y="236" width="8" height="8"/><rect x="578" y="236" width="8" height="8"/><rect x="590" y="236" width="8" height="8"/><rect x="602" y="236" width="8" height="8"/><rect x="614" y="236" width="8" height="8"/><rect x="626" y="236" width="8" height="8"/><rect x="638" y="236" width="8" height="8"/><rect x="650" y="236" width="8" height="8"/><rect x="662" y="236" width="8" height="8"/><rect x="674" y="236" width="8" height="8"/><rect x="686" y="236" width="8" height="8"/><rect x="698" y="236" width="8" height="8"/><rect x="710" y="236" width="8" height="8"/><rect x="722" y="236" width="8" height="8"/><rect x="734" y="236" width="8" height="8"/><rect x="746" y="236" width="8" height="8"/><rect x="758" y="236" width="8" height="8"/><rect x="770" y="236" width="8" height="8"/><rect x="782" y="236" width="8" height="8"/><rect x="794" y="236" width="8" height="8"/><rect x="806" y="236" width="8" height="8"/><rect x="818" y="236" width="8" height="8"/><rect x="830" y="236" width="8" height="8"/><rect x="842" y="236" width="8" height="8"/><rect x="854" y="236" width="8" height="8"/>
      <rect x="482" y="248" width="8" height="8"/><rect x="494" y="248" width="8" height="8"/><rect x="506" y="248" width="8" height="8"/><rect x="518" y="248" width="8" height="8"/><rect x="530" y="248" width="8" height="8"/><rect x="542" y="248" width="8" height="8"/><rect x="554" y="248" width="8" height="8"/><rect x="566" y="248" width="8" height="8"/><rect x="578" y="248" width="8" height="8"/><rect x="590" y="248" width="8" height="8"/><rect x="602" y="248" width="8" height="8"/><rect x="614" y="248" width="8" height="8"/><rect x="626" y="248" width="8" height="8"/><rect x="638" y="248" width="8" height="8"/><rect x="650" y="248" width="8" height="8"/><rect x="662" y="248" width="8" height="8"/><rect x="674" y="248" width="8" height="8"/><rect x="686" y="248" width="8" height="8"/><rect x="698" y="248" width="8" height="8"/><rect x="710" y="248" width="8" height="8"/><rect x="722" y="248" width="8" height="8"/><rect x="734" y="248" width="8" height="8"/><rect x="746" y="248" width="8" height="8"/><rect x="758" y="248" width="8" height="8"/><rect x="770" y="248" width="8" height="8"/><rect x="782" y="248" width="8" height="8"/><rect x="794" y="248" width="8" height="8"/><rect x="806" y="248" width="8" height="8"/><rect x="818" y="248" width="8" height="8"/><rect x="830" y="248" width="8" height="8"/><rect x="842" y="248" width="8" height="8"/><rect x="854" y="248" width="8" height="8"/>
      <rect x="482" y="260" width="8" height="8"/><rect x="494" y="260" width="8" height="8"/><rect x="506" y="260" width="8" height="8"/><rect x="518" y="260" width="8" height="8"/><rect x="530" y="260" width="8" height="8"/><rect x="542" y="260" width="8" height="8"/><rect x="554" y="260" width="8" height="8"/><rect x="566" y="260" width="8" height="8"/><rect x="578" y="260" width="8" height="8"/><rect x="590" y="260" width="8" height="8"/><rect x="602" y="260" width="8" height="8"/><rect x="614" y="260" width="8" height="8"/><rect x="626" y="260" width="8" height="8"/><rect x="638" y="260" width="8" height="8"/><rect x="650" y="260" width="8" height="8"/><rect x="662" y="260" width="8" height="8"/><rect x="674" y="260" width="8" height="8"/><rect x="686" y="260" width="8" height="8"/><rect x="698" y="260" width="8" height="8"/><rect x="710" y="260" width="8" height="8"/><rect x="722" y="260" width="8" height="8"/><rect x="734" y="260" width="8" height="8"/><rect x="746" y="260" width="8" height="8"/><rect x="758" y="260" width="8" height="8"/><rect x="770" y="260" width="8" height="8"/><rect x="782" y="260" width="8" height="8"/><rect x="794" y="260" width="8" height="8"/><rect x="806" y="260" width="8" height="8"/><rect x="818" y="260" width="8" height="8"/><rect x="830" y="260" width="8" height="8"/><rect x="842" y="260" width="8" height="8"/><rect x="854" y="260" width="8" height="8"/>
      <rect x="482" y="272" width="8" height="8"/><rect x="494" y="272" width="8" height="8"/><rect x="506" y="272" width="8" height="8"/><rect x="518" y="272" width="8" height="8"/><rect x="530" y="272" width="8" height="8"/><rect x="542" y="272" width="8" height="8"/><rect x="554" y="272" width="8" height="8"/><rect x="566" y="272" width="8" height="8"/><rect x="578" y="272" width="8" height="8"/><rect x="590" y="272" width="8" height="8"/><rect x="602" y="272" width="8" height="8"/><rect x="614" y="272" width="8" height="8"/><rect x="626" y="272" width="8" height="8"/><rect x="638" y="272" width="8" height="8"/><rect x="650" y="272" width="8" height="8"/><rect x="662" y="272" width="8" height="8"/><rect x="674" y="272" width="8" height="8"/><rect x="686" y="272" width="8" height="8"/><rect x="698" y="272" width="8" height="8"/><rect x="710" y="272" width="8" height="8"/><rect x="722" y="272" width="8" height="8"/><rect x="734" y="272" width="8" height="8"/><rect x="746" y="272" width="8" height="8"/><rect x="758" y="272" width="8" height="8"/><rect x="770" y="272" width="8" height="8"/><rect x="782" y="272" width="8" height="8"/><rect x="794" y="272" width="8" height="8"/><rect x="806" y="272" width="8" height="8"/><rect x="818" y="272" width="8" height="8"/><rect x="830" y="272" width="8" height="8"/><rect x="842" y="272" width="8" height="8"/><rect x="854" y="272" width="8" height="8"/>
      <rect x="482" y="284" width="8" height="8"/><rect x="494" y="284" width="8" height="8"/><rect x="506" y="284" width="8" height="8"/><rect x="518" y="284" width="8" height="8"/><rect x="530" y="284" width="8" height="8"/><rect x="542" y="284" width="8" height="8"/><rect x="554" y="284" width="8" height="8"/><rect x="566" y="284" width="8" height="8"/><rect x="578" y="284" width="8" height="8"/><rect x="590" y="284" width="8" height="8"/><rect x="602" y="284" width="8" height="8"/><rect x="614" y="284" width="8" height="8"/><rect x="626" y="284" width="8" height="8"/><rect x="638" y="284" width="8" height="8"/><rect x="650" y="284" width="8" height="8"/><rect x="662" y="284" width="8" height="8"/><rect x="674" y="284" width="8" height="8"/><rect x="686" y="284" width="8" height="8"/><rect x="698" y="284" width="8" height="8"/><rect x="710" y="284" width="8" height="8"/><rect x="722" y="284" width="8" height="8"/><rect x="734" y="284" width="8" height="8"/><rect x="746" y="284" width="8" height="8"/><rect x="758" y="284" width="8" height="8"/><rect x="770" y="284" width="8" height="8"/><rect x="782" y="284" width="8" height="8"/><rect x="794" y="284" width="8" height="8"/><rect x="806" y="284" width="8" height="8"/><rect x="818" y="284" width="8" height="8"/><rect x="830" y="284" width="8" height="8"/><rect x="842" y="284" width="8" height="8"/><rect x="854" y="284" width="8" height="8"/>
    </g>

    <g text-anchor="middle" fill="currentColor" font-size="8" opacity="0.65">
      <text x="228" y="312">8 drawn here — the lesson's range is 4–16</text>
      <text x="672" y="312">384 tiny squares drawn here — a real GPU has thousands</text>
    </g>

    <g text-anchor="middle" fill="currentColor" font-size="9">
      <text x="228" y="334">GOOD at complex, varied tasks done quickly,</text>
      <text x="228" y="348">one after another — branchy, sequential, decision-heavy</text>
      <text x="228" y="362">logic, like handling a single web request.</text>
      <text x="672" y="334">GOOD at lots of similar little tasks, all at the SAME TIME.</text>
      <text x="672" y="348">Each core is weaker and less flexible. BAD at branchy,</text>
      <text x="672" y="362">sequential, one-off logic — that stays on the CPU.</text>
    </g>
    <g text-anchor="middle" fill="currentColor" font-size="8.5" opacity="0.7">
      <text x="228" y="376">a few expert chefs, each cooking any dish start to finish</text>
      <text x="672" y="376">a huge line of cooks, each doing one step on a different plate</text>
    </g>

    <rect x="16" y="406" width="868" height="112" rx="11" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
    <text x="450" y="430" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">SIMD — Single Instruction, Multiple Data: one operation across thousands of data items at once</text>
    <path d="M450 442 L450 508" fill="none" stroke="currentColor" stroke-opacity="0.2" stroke-width="1"/>
    <g text-anchor="middle" fill="currentColor">
      <text x="233" y="458" font-size="10" font-weight="700">GRAPHICS — where GPUs came from</text>
      <text x="233" y="476" font-size="9">a screen is millions of pixels, and each pixel</text>
      <text x="233" y="490" font-size="9">is computed the same way, independently</text>
      <text x="233" y="508" font-size="8.5" opacity="0.7">millions of identical, independent little jobs</text>

      <text x="667" y="458" font-size="10" font-weight="700">AI — the exact same shape</text>
      <text x="667" y="476" font-size="9">a neural network is mostly matrix multiplication:</text>
      <text x="667" y="490" font-size="9">millions of identical multiply-and-adds, all independent</text>
      <text x="667" y="508" font-size="8.5" opacity="0.7">which is why AI training and inference runs on GPUs</text>
    </g>
  </g>
  <text x="450" y="548" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="11" font-weight="700" fill="currentColor">Rule of thumb: lots of identical math on lots of data → GPU. Varied, sequential, decision-heavy logic → CPU.</text>
  <text x="450" y="572" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Most web backends run entirely on CPUs — handling a request is branchy, sequential work, not parallel math.</text>
  <text x="450" y="591" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">GPUs enter for machine-learning inference, video transcoding, and large-scale data crunching.</text>
  <text x="450" y="614" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">The size ratio above is the message: big-and-few buys latency, small-and-many buys throughput.</text>
</svg>
```

The CPU optimizes for **latency** (finish one complex task fast); the GPU optimizes for
**throughput** (finish a huge pile of similar tasks per second).

### Where the GPU came from — and why AI loves it

GPUs were built for **graphics**: a screen is millions of pixels, and each pixel is
computed the *same way*, independently. That's a perfect fit for doing **one operation
across thousands of data items at once** (the idea is called SIMD — Single Instruction,
Multiple Data).

It turns out **AI has the exact same shape**. A neural network is, underneath, mostly
**matrix multiplication** — millions of identical small multiply-and-add operations, all
independent. That's precisely what a GPU eats for breakfast, which is why training and
running large AI models happens on GPUs, not CPUs.

### The trade-off (this is the whole lesson)

A GPU is spectacular when work is **(1) highly parallel** and **(2) the same operation over
lots of data**. It's *bad* at branchy, sequential, one-off logic — decisions, "if this then
that," handling a single web request. That's the CPU's job. There's also a cost to shipping
data to and from the GPU, so tiny jobs aren't worth it.

**Rule of thumb:** lots of identical math on lots of data → GPU. Varied, sequential,
decision-heavy logic → CPU.

### Why GPUs are so expensive

High-end GPUs are among the priciest chips made: they're **physically huge dies** (more
silicon, lower yield — lesson 4), carry **large amounts of fast on-board memory** (**VRAM**, video RAM),
and are in ferocious demand for AI. So the price reflects big-chip economics *plus* a
supply-and-demand squeeze.

### What this means for a backend engineer

Most web backends run entirely on **CPUs** — handling a request is branchy, sequential
work, not parallel math. GPUs enter the picture for specific workloads: **machine-learning
inference, video transcoding, large-scale data crunching**. Knowing the difference means
you won't rent an expensive GPU box to serve **JSON** (JavaScript Object Notation, a common
text data format), and you won't try to run a heavy ML model
on a CPU and wonder why it crawls.

## Think about it

1. In the chef analogy, why would you *not* want 4,000 line cooks to prepare one intricate
   seven-course tasting menu for a single guest?
2. Neural networks are mostly matrix multiplication. Why does that make them a great fit for
   a GPU?
3. You're building a normal web **API** (application programming interface) that reads and
   writes a database. CPU or GPU — and why?

## Key takeaways

- A **CPU** has a *few powerful cores* tuned for **latency** (finish one complex task fast);
  a **GPU** has *thousands of simple cores* tuned for **throughput** (finish a huge pile of
  similar tasks).
- GPUs excel at **highly parallel, same-operation-over-much-data** work — graphics and the
  matrix math inside **AI**. They're poor at branchy, sequential logic.
- GPUs are measured differently (FLOPS — floating-point ops per second) and are **expensive**
  (huge dies, fast VRAM, AI demand).
- **Backends mostly use CPUs**; reach for a GPU only for parallel-math workloads (ML,
  video, big data).

Next: [Comparing Hardware](../08-comparing-hardware/) — the units and numbers that let you
compare a CPU, a GPU, RAM, and storage on the same page.
