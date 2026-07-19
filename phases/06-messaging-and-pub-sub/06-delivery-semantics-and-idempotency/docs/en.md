# Delivery Semantics & Idempotent Consumers

> A customer is charged twice, and nothing broke. The broker followed its contract, the consumer followed its contract, the network dropped one packet on the way back, and ninety rupees left an account that owed nothing. This lesson proves that exactly-once *delivery* is impossible — not hard, impossible — and then builds the thing that actually works: a consumer for which being told twice and being told once produce the same result.

**Type:** Build
**Languages:** Python
**Prerequisites:** [The Log: Offsets, Replay & Retention](../05-the-log-offsets-and-replay/)
**Time:** ~80 minutes

## The Problem

Your `payments` consumer reads a queue. Each message says *charge card X, $90.00, for order 1042*. It has run in production for eight months. It has never thrown an exception, never dead-lettered a message, never paged anyone. Its dashboards are green.

Support has 340 open tickets about double charges.

Here is the entire incident, at millisecond resolution, with **no component malfunctioning**:

```text
t=   0 ms  BROKER    delivers charge:order-1042, starts a 500 ms lease
t=  12 ms  CONSUMER  receives it, begins work
t= 140 ms  CONSUMER  charges the card. $90.00 moves. Success.
t= 141 ms  CONSUMER  sends the ack
t= 141 ms  NETWORK   the ack packet is dropped
t= 500 ms  BROKER    lease expires, no ack seen
t= 500 ms  BROKER    redelivers charge:order-1042      <- correct behaviour
t= 640 ms  CONSUMER  charges the card AGAIN. $90.00 moves again.
```

Read the seventh line again. The broker did **the right thing**. Its contract is: hand out a message, wait for confirmation, and if no confirmation arrives before the lease expires, assume the consumer died and hand the message to somebody else. That is the only contract a broker *can* have — a broker that deleted messages it wasn't sure had been processed would lose payments, which is worse. The redelivery is not a bug. It is the feature working.

The consumer also did the right thing. It received a message, it did the work, it acknowledged. Both times. It has no way of knowing the second delivery is a repeat of the first, because from the consumer's point of view the two deliveries are byte-identical instructions to charge a card.

The network did not malfunction either. Packets are dropped. That is what packets do. On a link with 99.99% ack reliability — which would be an excellent link — at 5,000 messages/second, that is one dropped ack every two seconds: **43,200 a day**, every one of which is a redelivery, and every one of which is a potential double charge.

So who is at fault? Nobody. And that is the point: this is not a bug you can fix by fixing a component. It is a property of sending messages over a network you do not control.

Now watch the obvious fix make it worse. "Fine," you say, "acknowledge *first*, then do the work — then a lost ack can't cause a redelivery."

```text
t=   0 ms  BROKER    delivers charge:order-1042
t=  13 ms  CONSUMER  sends the ack BEFORE doing the work
t=  26 ms  BROKER    ack received, message deleted    <- no copy remains anywhere
t=  30 ms  CONSUMER  process is OOM-killed mid-deploy
t= 500 ms  BROKER    nothing to redeliver: the queue is empty
```

The charge never happens. The order sits in "paid" state with no payment behind it. There is no error, no alert, no dead letter, no ticket — because from every system's perspective the message was handled. This bug is strictly harder to find than the first one, because the first one generates 340 angry customers and this one generates silence.

The acknowledgement is the only lever you have, and it has exactly two positions:

- **Ack before the work** — you may lose the effect, you will never duplicate it.
- **Ack after the work** — you may duplicate the effect, you will never lose it.

There is no third position. Choosing where to put the ack is choosing **which bug you get**, not whether you get one. Everything in this lesson follows from accepting that sentence.

## The Concept

### The three delivery semantics, and the single line of code that picks one

A **delivery guarantee** (or *delivery semantic*) is a statement about how many times a message can be handed to a consumer relative to how many times it was published. There are three, and they are not three points on a dial you tune — the first two are defined entirely by where the acknowledgement sits, and the third is a claim you have to interrogate.

**At-most-once.** The consumer acknowledges before it does the work, or the broker deletes the message the moment it puts it on the wire (often called *auto-ack* or *fire-and-forget*). Every message is handed out zero or one times. **Nothing is ever duplicated. Things are lost.** Losses happen whenever the network eats the delivery, or the consumer dies between receiving and finishing.

This is the correct choice more often than payments engineers assume. A metrics data point, a heartbeat, a "user is typing" notification, a position update in a game — the next message supersedes this one within seconds, and the cost of a duplicate (a double-counted metric, a corrupted gauge) exceeds the cost of a gap. Choose at-most-once *deliberately*, and be able to say what percentage of loss you are buying.

**At-least-once.** The consumer does the work, then acknowledges. The broker holds the message under a **lease** — the *visibility timeout* from [Lesson 3](../03-build-a-message-queue/) — and redelivers if no ack arrives in time. Every message is handed out one or more times. **Nothing is ever lost. Things are duplicated.**

This is the practical default for almost everything, and every broker in the phase's `Use It` sections ships it as the default. Notice why: at-least-once has a *recovery story* (the duplicate can be neutralised by the consumer) and at-most-once does not (the loss cannot be recovered by anyone, because no copy exists). Given a choice between a problem the application can solve and a problem nobody can solve, take the first one.

**Exactly-once.** Every message is handed out precisely once. This is the one on the marketing page, and the rest of this lesson is about what it actually means.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 508" width="100%" style="max-width:840px" role="img" aria-label="Three consumer strategies compared by where the acknowledgement sits relative to the work. Acknowledging first loses four charges worth 688 rupees. Acknowledging last duplicates seven charges worth 1466 rupees. Acknowledging last with an atomic idempotency claim receives the identical 47 deliveries as the naive run and lands on the exact expected balance of 8197 rupees.">
  <defs>
    <marker id="l06-arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Where the ack sits is the whole decision — 40 charges, measured</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="848" height="134" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="16" y="190" width="848" height="134" rx="13" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff"/>
    <rect x="16" y="336" width="848" height="134" rx="13" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="248" y="98" width="94" height="42" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="356" y="98" width="104" height="42" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    <rect x="474" y="98" width="104" height="42" rx="8" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
    <rect x="596" y="66" width="252" height="94" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>

    <rect x="248" y="244" width="94" height="42" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="356" y="244" width="104" height="42" rx="8" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    <rect x="474" y="244" width="104" height="42" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    <rect x="596" y="212" width="252" height="94" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>

    <rect x="248" y="390" width="94" height="42" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="356" y="390" width="104" height="42" rx="8" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f"/>
    <rect x="474" y="390" width="104" height="42" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    <rect x="596" y="358" width="252" height="94" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M342 119 L 350 119" marker-end="url(#l06-arrow)"/>
    <path d="M460 119 L 468 119" marker-end="url(#l06-arrow)"/>
    <path d="M342 265 L 350 265" marker-end="url(#l06-arrow)"/>
    <path d="M460 265 L 468 265" marker-end="url(#l06-arrow)"/>
    <path d="M342 411 L 350 411" marker-end="url(#l06-arrow)"/>
    <path d="M460 411 L 468 411" marker-end="url(#l06-arrow)"/>
    <path d="M526 286 L 526 306 L 295 306 L 295 288" marker-end="url(#l06-arrow)" stroke-dasharray="5 4"/>
    <path d="M526 432 L 526 452 L 295 452 L 295 434" marker-end="url(#l06-arrow)" stroke-dasharray="5 4"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="34" y="76" font-size="12.5" font-weight="700" fill="#e0930f">AT-MOST-ONCE</text>
    <text x="34" y="95" font-size="9.5" opacity="0.9">ack BEFORE the work</text>
    <text x="34" y="112" font-size="9" opacity="0.75">auto-ack · fire and forget</text>
    <text x="34" y="132" font-size="9" opacity="0.75">the broker keeps no copy</text>
    <text x="295" y="124" font-size="10" font-weight="700" text-anchor="middle">RECEIVE</text>
    <text x="408" y="124" font-size="10" font-weight="700" text-anchor="middle">ACK</text>
    <text x="526" y="118" font-size="10" font-weight="700" text-anchor="middle">WORK</text>
    <text x="526" y="133" font-size="8" text-anchor="middle" opacity="0.85">crash = gone</text>
    <text x="612" y="88" font-size="10.5" font-weight="700">may LOSE · never duplicates</text>
    <text x="612" y="110" font-size="9.5" opacity="0.9">4 of 40 charges never happened</text>
    <text x="612" y="128" font-size="11" font-weight="700" fill="#e0930f">balance 7,509.00  (-688.00)</text>
    <text x="612" y="148" font-size="9" opacity="0.8">silent: no error, no dead letter</text>

    <text x="34" y="222" font-size="12.5" font-weight="700" fill="#7c5cff">AT-LEAST-ONCE (naive)</text>
    <text x="34" y="241" font-size="9.5" opacity="0.9">ack AFTER the work</text>
    <text x="34" y="258" font-size="9" opacity="0.75">the broker holds a lease</text>
    <text x="34" y="278" font-size="9" opacity="0.75">the practical default</text>
    <text x="295" y="270" font-size="10" font-weight="700" text-anchor="middle">RECEIVE</text>
    <text x="408" y="264" font-size="10" font-weight="700" text-anchor="middle">WORK</text>
    <text x="408" y="279" font-size="8" text-anchor="middle" opacity="0.85">card charged</text>
    <text x="526" y="270" font-size="10" font-weight="700" text-anchor="middle">ACK</text>
    <text x="410" y="320" font-size="8.5" text-anchor="middle" opacity="0.9">ack lost -> lease expires -> redelivered (7 times)</text>
    <text x="612" y="234" font-size="10.5" font-weight="700">never loses · MAY DUPLICATE</text>
    <text x="612" y="256" font-size="9.5" opacity="0.9">7 cards charged twice</text>
    <text x="612" y="274" font-size="11" font-weight="700" fill="#7c5cff">balance 9,663.00  (+1,466.00)</text>
    <text x="612" y="294" font-size="9" opacity="0.8">every log line still says 'success'</text>

    <text x="34" y="368" font-size="12.5" font-weight="700" fill="#0fa07f">AT-LEAST-ONCE + IDEMPOTENT</text>
    <text x="34" y="387" font-size="9.5" opacity="0.9">ack AFTER the work</text>
    <text x="34" y="404" font-size="9" opacity="0.75">the work CLAIMS the key first,</text>
    <text x="34" y="421" font-size="9" opacity="0.75">in the same transaction</text>
    <text x="295" y="416" font-size="10" font-weight="700" text-anchor="middle">RECEIVE</text>
    <text x="408" y="410" font-size="9.5" font-weight="700" text-anchor="middle">CLAIM+WORK</text>
    <text x="408" y="425" font-size="8" text-anchor="middle" opacity="0.85">one transaction</text>
    <text x="526" y="416" font-size="10" font-weight="700" text-anchor="middle">ACK</text>
    <text x="410" y="466" font-size="8.5" text-anchor="middle" opacity="0.9">the SAME 7 redeliveries arrive — and the claim rejects all 7</text>
    <text x="612" y="380" font-size="10.5" font-weight="700">never loses · duplicates do nothing</text>
    <text x="612" y="402" font-size="9.5" opacity="0.9">identical 47 deliveries as above</text>
    <text x="612" y="420" font-size="11" font-weight="700" fill="#0fa07f">balance 8,197.00  (exact)</text>
    <text x="612" y="440" font-size="9" opacity="0.8">the delivery layer did not change</text>

    <text x="440" y="492" font-size="10.5" text-anchor="middle" opacity="0.95">Rows 2 and 3 received byte-identical traffic. Only the consumer changed — and that is where correctness lives.</text>
  </g>
</svg>
```

### Why exactly-once delivery is impossible

This is not an engineering limitation waiting for a better broker. It is a proof, it is fifty years old, and being able to state it is the difference between believing a vendor and evaluating one.

Start with what the broker in The Problem actually knows at `t=499 ms`. It sent a message. It has received no acknowledgement. It is now in one of two worlds:

- **World A** — the message never arrived. The consumer has done nothing. If the broker gives up now, the charge never happens.
- **World B** — the message arrived, the card was charged, and the *acknowledgement* was lost on the way back. If the broker resends now, the card is charged twice.

**These two worlds are indistinguishable from the broker's position.** The evidence available to it — silence — is exactly the same in both. No amount of waiting resolves it, because "no reply yet" and "no reply ever" also look identical under asynchrony. No additional message resolves it either, and that last claim is the one that needs proving.

This is the **Two Generals Problem**, first stated by Akkoyunlu, Ekanadham and Huber in "Some Constraints and Trade-offs in the Design of Network Communications" (*Proceedings of the 5th ACM Symposium on Operating Systems Principles*, 1975), and given its familiar name by Jim Gray in "Notes on Data Base Operating Systems" (1978). Two generals on opposite hills must attack at the same time to win; they can only communicate by messengers who cross enemy territory and may be captured. General A sends "attack at dawn". Did it arrive? He needs an acknowledgement. B sends one. Did *that* arrive? B cannot know, so B needs an acknowledgement of the acknowledgement. And so on.

The proof is a short argument by contradiction. Suppose some finite protocol exists that guarantees both generals reach certainty. Take the shortest such protocol, and look at its final message. That message could be lost — the channel is unreliable, so every message can be. If the protocol is still correct when the final message is lost, then the final message was never needed, and deleting it yields a shorter correct protocol, contradicting minimality. If the protocol is *not* correct when the final message is lost, then it never guaranteed certainty in the first place. Either way, no such protocol exists. **Not "we haven't found one yet" — cannot exist.**

Map it back and nothing has changed but the vocabulary. The broker is a general. The consumer is a general. "Attack at dawn" is "charge this card". The channel is your VPC (Virtual Private Cloud), which drops packets. The sender that receives no acknowledgement must choose:

- **Resend** — guaranteeing delivery, accepting duplicates. That is at-least-once.
- **Do not resend** — guaranteeing no duplicates, accepting loss. That is at-most-once.

There is no option three, because option three would be the protocol that provably does not exist.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="The Two Generals Problem applied to a broker. In world A the message is lost and no charge happened; in world B the message arrived, the card was charged, and the acknowledgement was lost. The broker observes silence in both worlds and cannot tell them apart, so it must choose between resending, which duplicates in world B, and not resending, which loses in world A.">
  <defs>
    <marker id="l06-arrow2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Two worlds, one observation — the broker cannot tell them apart</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="418" height="176" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="446" y="44" width="418" height="176" rx="13" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff"/>
    <rect x="16" y="236" width="848" height="52" rx="11" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="16" y="308" width="418" height="112" rx="12" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
    <rect x="446" y="308" width="418" height="112" rx="12" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="40" y="120" width="86" height="44" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    <rect x="322" y="120" width="90" height="44" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="470" y="120" width="86" height="44" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    <rect x="752" y="120" width="90" height="44" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.7">
    <path d="M126 134 L 200 134"/>
    <path d="M556 134 L 746 134" marker-end="url(#l06-arrow2)"/>
    <path d="M746 156 L 620 156"/>
    <path d="M440 230 L 440 236"/>
    <path d="M225 288 L 225 302" marker-end="url(#l06-arrow2)"/>
    <path d="M655 288 L 655 302" marker-end="url(#l06-arrow2)"/>
  </g>
  <g fill="none" stroke="#e0930f" stroke-width="2.6">
    <path d="M204 124 L 224 144"/>
    <path d="M224 124 L 204 144"/>
  </g>
  <g fill="none" stroke="#7c5cff" stroke-width="2.6">
    <path d="M600 146 L 620 166"/>
    <path d="M620 146 L 600 166"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="34" y="72" font-size="12.5" font-weight="700" fill="#e0930f">WORLD A — the message died</text>
    <text x="34" y="92" font-size="9.5" opacity="0.85">forward path lost the packet</text>
    <text x="83" y="147" font-size="10" font-weight="700" text-anchor="middle">BROKER</text>
    <text x="214" y="182" font-size="9" text-anchor="middle" fill="#e0930f" font-weight="700">dropped</text>
    <text x="367" y="141" font-size="10" font-weight="700" text-anchor="middle" opacity="0.5">CONSUMER</text>
    <text x="367" y="156" font-size="8.5" text-anchor="middle" opacity="0.5">saw nothing</text>
    <text x="225" y="206" font-size="9.5" text-anchor="middle" opacity="0.95">card NOT charged</text>

    <text x="464" y="72" font-size="12.5" font-weight="700" fill="#7c5cff">WORLD B — the ack died</text>
    <text x="464" y="92" font-size="9.5" opacity="0.85">return path lost the packet</text>
    <text x="513" y="147" font-size="10" font-weight="700" text-anchor="middle">BROKER</text>
    <text x="797" y="141" font-size="10" font-weight="700" text-anchor="middle">CONSUMER</text>
    <text x="797" y="156" font-size="8.5" text-anchor="middle">charged 90.00</text>
    <text x="610" y="186" font-size="9" text-anchor="middle" fill="#7c5cff" font-weight="700">dropped</text>
    <text x="655" y="206" font-size="9.5" text-anchor="middle" opacity="0.95">card ALREADY charged</text>

    <text x="440" y="258" font-size="12" font-weight="700" text-anchor="middle" fill="#3553ff">WHAT THE BROKER OBSERVES IN BOTH WORLDS:  silence</text>
    <text x="440" y="276" font-size="9.5" text-anchor="middle" opacity="0.9">no message distinguishes them — the proof: the last message of any finite protocol can itself be lost</text>

    <text x="225" y="334" font-size="12" font-weight="700" text-anchor="middle" fill="#7c5cff">RESEND</text>
    <text x="225" y="356" font-size="9.5" text-anchor="middle" opacity="0.95">correct in world A</text>
    <text x="225" y="374" font-size="9.5" text-anchor="middle" opacity="0.95">DOUBLE CHARGE in world B</text>
    <text x="225" y="400" font-size="10.5" text-anchor="middle" font-weight="700">= AT-LEAST-ONCE</text>

    <text x="655" y="334" font-size="12" font-weight="700" text-anchor="middle" fill="#e0930f">DO NOT RESEND</text>
    <text x="655" y="356" font-size="9.5" text-anchor="middle" opacity="0.95">correct in world B</text>
    <text x="655" y="374" font-size="9.5" text-anchor="middle" opacity="0.95">MONEY NEVER MOVES in world A</text>
    <text x="655" y="400" font-size="10.5" text-anchor="middle" font-weight="700">= AT-MOST-ONCE</text>

    <text x="440" y="446" font-size="10.5" text-anchor="middle" opacity="0.95">Two Generals (Akkoyunlu, Ekanadham &amp; Huber, SOSP 1975). There is no third branch to build.</text>
    <text x="440" y="464" font-size="9.5" text-anchor="middle" opacity="0.75">Related: Fischer, Lynch &amp; Paterson (JACM 1985) — no deterministic consensus under asynchrony with one crash fault.</text>
  </g>
</svg>
```

A neighbouring impossibility is worth naming because it gets confused with this one. **Fischer, Lynch and Paterson**, "Impossibility of Distributed Consensus with One Faulty Process" (*Journal of the ACM*, 32(2), 1985), proves that in an asynchronous system — no bound on message delay — no *deterministic* algorithm can guarantee that all correct processes agree on a value, if even one process may crash. The intuition is the same shape as Two Generals: you cannot distinguish "crashed" from "slow", so any protocol that waits can wait forever, and any protocol that gives up can be wrong. FLP is about **consensus**, Two Generals is about **reliable delivery over a lossy channel**; they are different results with a common root, which is that under asynchrony, *silence carries no information*.

### The distinction that resolves the myth: delivery versus effect

Now the sentence that separates a senior engineer from a confident one:

> Exactly-once **delivery** over an unreliable network is impossible. Exactly-once **processing** — more precisely, exactly-once **effect** — is entirely achievable.

The message may arrive one time, or five times, and you cannot control that. What you can control is whether the second, third and fifth arrivals **change anything**. If they do not, then the observable state of your system is identical to a world in which the message arrived exactly once. The user was charged once. The email count is one. The stock decrement happened once. That is what anybody actually wanted when they asked for exactly-once; nobody cares how many packets crossed the wire.

Whenever a product advertises exactly-once, it is selling one of exactly two mechanisms, and both are worth understanding because neither is magic:

1. **At-least-once delivery plus deduplication.** The system delivers redundantly and remembers what it has already seen, discarding repeats. This is the common case, and its correctness is entirely bounded by how long and how completely it remembers — which is [the dedup window problem](#the-dedup-window-a-ttl-is-a-correctness-boundary), below.
2. **A transaction that atomically couples the position commit with the effect.** The offset advance from [Lesson 5](../05-the-log-offsets-and-replay/) and the state change land in one atomic commit, so there is no interval in which one has happened and the other has not. This is genuinely exactly-once, and it works only when the effect lives somewhere that can participate in that transaction.

Neither mechanism reaches outside your system. Both are described honestly further down. When you hear "exactly-once", the correct follow-up question is not *"really?"* — it is **"which of the two, and what is the scope?"**

### Idempotency: the actual answer

An operation is **idempotent** if applying it more than once has the same effect as applying it once. Formally, `f(f(x)) = f(x)` for all `x`. The word comes from mathematics — *idem* (same) + *potens* (power) — and it is the same property you met in [Phase 2, Lesson 7](../../02-api-design/07-idempotency-safe-retries/), where a client retrying a `POST` after a timeout needed the server to not charge twice. That was one client and one server; this is a broker fanning redeliveries at a consumer pool. **The problem is identical and so is the fix**, which is a good sign that you are looking at something fundamental rather than a framework quirk.

An idempotent consumer converts at-least-once *delivery* into exactly-once *effect*. That is the whole game, and here is the taxonomy for achieving it, in preference order — the cheapest and most robust first.

**1. Make the operation naturally idempotent.** The best dedup store is the one you did not need. Look at the shape of the write:

```sql
-- NOT idempotent: relative. Applying it twice moves twice as much.
UPDATE accounts SET balance = balance - 90.00 WHERE id = 42;

-- Idempotent: absolute. Applying it twice lands in the same place.
UPDATE orders SET status = 'shipped', shipped_at = '2026-07-18T09:14:00Z' WHERE id = 1042;
```

The distinction is **relative versus absolute**. A relative operation (`+= 10`, `append`, `increment`) composes with itself and is never idempotent. An absolute operation (`SET status = 'shipped'`, `SET price = 499`, `PUT` the whole document) overwrites, and running it twice with the same input is indistinguishable from running it once. `DELETE FROM x WHERE id = 7` is idempotent. `INSERT` is not — unless you give it a unique key, which is the next item.

You can often *restructure* a relative operation into an absolute one. Instead of "add $90 to the ledger", write "record ledger entry `charge:order-1042` with amount $90", and derive the balance by summing entries — an append-only, event-sourced shape where the primary key of the entry gives you idempotency for free. This is not always available, but ask before reaching for machinery.

**2. Idempotency key plus a dedup store.** When the operation cannot be made naturally idempotent, keep a record of what you have processed. The key is the `message_id` from [Lesson 2](../02-anatomy-of-a-message/) — but read the producer-side section below before deciding what goes in it, because the choice of key is where most implementations quietly break. The naive shape of this is also *wrong*, in a way that passes code review and passes tests: see the atomicity trap.

**3. Conditional writes and optimistic concurrency.** Attach a version to the row and make the write conditional on it:

```sql
UPDATE orders SET status = 'shipped', version = 8
 WHERE id = 1042 AND version = 7;      -- 0 rows updated => somebody got here first
```

The database checks and writes in one atomic step, and the affected-row count tells you whether you were the one who did it. This is **compare-and-set** (CAS) — the same idea as an HTTP `If-Match` with an `ETag`, or DynamoDB's `ConditionExpression`. It needs no extra table.

**4. Fencing tokens and monotonic sequence numbers.** Attach a number that only ever increases, and reject anything not greater than what you have already applied:

```sql
UPDATE inventory SET qty = 40, last_seq = 118
 WHERE sku = 'AX-9' AND last_seq < 118;   -- a replayed seq 117 changes nothing
```

This rejects not only duplicates but **stale** work — the delayed redelivery of an older message that would otherwise overwrite newer state, a distinct and nastier bug than a plain duplicate. Fencing tokens are the standard defence against a paused-then-resumed worker whose lease was already reassigned: it comes back, writes with an old token, and the storage layer refuses. Sequence numbers need ordering to be meaningful, which is [Lesson 7](../07-ordering-partition-keys-and-parallel-consumers/).

### The atomicity trap: check-then-act is itself a race

Here is the implementation nearly everyone writes first:

```python
if dedup_store.contains(msg.id):      # 1. check
    return
charge_card(msg.account, msg.amount)  # 2. act
dedup_store.record(msg.id)            # 3. remember
```

It is wrong. Not "wrong under exotic conditions" — wrong under the single most ordinary condition in the entire phase: **two consumer instances holding the same message at the same time.** That happens whenever a lease expires while a consumer is still working, which happens whenever a consumer is slower than expected, which happens every day.

Trace it:

```text
A: contains(id)?  -> False
B: contains(id)?  -> False      <- both passed the check
A: charge_card()                 first charge
B: charge_card()                 SECOND CHARGE
A: record(id)
B: record(id)
```

The dedup store worked perfectly. It was consulted correctly and answered correctly. The bug is the **gap** between step 1 and step 3 — a window another worker fits into entirely. Adding a lock around it moves the problem rather than solving it, because a distributed lock has its own lease and its own expiry, and now you have two leases that can disagree.

The fix is to remove the gap by making the dedup record and the effect **one atomic commit**:

```sql
BEGIN;
  INSERT INTO processed_messages (message_id, processed_at)
       VALUES ('charge:order-1042', now());     -- PRIMARY KEY / UNIQUE
  UPDATE accounts SET balance = balance - 9000 WHERE id = 42;
COMMIT;
```

If the insert violates the unique constraint, the whole transaction rolls back and no money moves. If it succeeds, both the record and the effect are durable together. There is no window, because **there is no check** — the unique constraint *is* the check, enforced by the one component in the system that can actually serialise two concurrent writers. In practice you write it as `INSERT ... ON CONFLICT DO NOTHING` (Postgres) or `INSERT IGNORE` (MySQL) and branch on the affected-row count, or you catch the integrity error.

Even better, when the shape allows it: skip the separate dedup table and put a **unique constraint on the natural business key**. A `payments` table with `UNIQUE (order_id)` needs no dedup infrastructure at all — the second insert fails, you catch it, you acknowledge the message, you move on. This is the humblest correct pattern in the whole lesson and it is almost always the right first answer.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="The atomicity trap. On the left, check-then-act lets two consumer instances both pass the dedup check before either records it, producing a balance of 180 rupees against an expected 90. On the right, a single transaction whose insert hits a unique constraint rejects the second instance and produces the correct balance of 90 rupees.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Same interleaving, same dedup store, two code shapes</text>
  <text x="440" y="46" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.85">A's lease expires while A is still working, so the broker hands the message to B. This is normal.</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="62" width="418" height="330" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="446" y="62" width="418" height="330" rx="13" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
    <rect x="40" y="316" width="370" height="56" rx="10" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="470" y="316" width="370" height="56" rx="10" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="40" y="146" width="370" height="24" rx="5" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-opacity="0.7"/>
    <rect x="40" y="202" width="370" height="24" rx="5" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-opacity="0.7"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="4 4" opacity="0.7">
    <path d="M52 134 L 398 134"/>
    <path d="M52 190 L 398 190"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="34" y="90" font-size="12.5" font-weight="700" fill="#e0930f">(a) CHECK-THEN-ACT</text>
    <text x="34" y="108" font-size="9" opacity="0.85">SELECT; if absent: UPDATE; INSERT</text>
    <text x="52" y="128" font-size="9.5">A: SELECT 1 FROM processed  -> 0 rows</text>
    <text x="52" y="162" font-size="9.5" font-weight="700">B: SELECT 1 FROM processed  -> 0 rows</text>
    <text x="404" y="162" font-size="8.5" text-anchor="end" font-weight="700" fill="#e0930f">both passed</text>
    <text x="52" y="184" font-size="9.5">A: UPDATE balances += 9000</text>
    <text x="52" y="218" font-size="9.5" font-weight="700">B: UPDATE balances += 9000</text>
    <text x="404" y="218" font-size="8.5" text-anchor="end" font-weight="700" fill="#e0930f">SECOND CHARGE</text>
    <text x="52" y="246" font-size="9.5">A: INSERT INTO processed (key)</text>
    <text x="52" y="266" font-size="9.5">B: INSERT INTO processed (key)  (no-op)</text>
    <text x="225" y="296" font-size="9" text-anchor="middle" opacity="0.9">the gap between SELECT and INSERT is a window</text>
    <text x="225" y="342" font-size="14" font-weight="700" text-anchor="middle">balance 180.00</text>
    <text x="225" y="362" font-size="10" text-anchor="middle" font-weight="700" fill="#e0930f">expected 90.00 — DOUBLE CHARGE</text>

    <text x="464" y="90" font-size="12.5" font-weight="700" fill="#0fa07f">(b) ONE TRANSACTION</text>
    <text x="464" y="108" font-size="9" opacity="0.85">BEGIN; INSERT (UNIQUE); UPDATE; COMMIT</text>
    <text x="482" y="134" font-size="9.5">A: BEGIN</text>
    <text x="482" y="154" font-size="9.5">A:   INSERT key            -> ok</text>
    <text x="482" y="174" font-size="9.5">A:   UPDATE balances += 9000</text>
    <text x="482" y="194" font-size="9.5">A: COMMIT</text>
    <text x="482" y="222" font-size="9.5">B: BEGIN</text>
    <text x="482" y="242" font-size="9.5" font-weight="700">B:   INSERT key  -> UNIQUE VIOLATION</text>
    <text x="482" y="262" font-size="9.5" font-weight="700">B: ROLLBACK — no money moved</text>
    <text x="655" y="296" font-size="9" text-anchor="middle" opacity="0.9">no check at all: the constraint IS the check</text>
    <text x="655" y="342" font-size="14" font-weight="700" text-anchor="middle">balance 90.00</text>
    <text x="655" y="362" font-size="10" text-anchor="middle" font-weight="700" fill="#0fa07f">expected 90.00 — CORRECT</text>

    <text x="440" y="418" font-size="10.5" text-anchor="middle" opacity="0.95">Only the database can serialise two writers. Any dedup check your code performs outside a transaction is advisory.</text>
    <text x="440" y="438" font-size="9.5" text-anchor="middle" opacity="0.75">The same reasoning as Phase 3's write-ahead log: atomicity is a storage-layer property, not an application-layer intention.</text>
  </g>
</svg>
```

### The dedup window: a TTL is a correctness boundary

Your dedup store cannot grow forever. A million messages a day at 60 bytes a key is 60 MB a day, 22 GB a year, and it is a hot lookup on every single message. So you give it a **TTL** (time to live) and expire old keys — Redis `SETEX`, a Postgres partition drop, DynamoDB's TTL attribute.

The moment you do that, you have converted your idempotency guarantee into a **conditional** one, and you must say the condition out loud:

> This consumer is idempotent **for redeliveries that arrive within the TTL**. A redelivery arriving after the TTL will be processed again.

That is not a caveat to bury. It is the actual guarantee. Size the window against your **worst realistic redelivery delay**, not your typical one, and enumerate the sources:

| Source of redelivery | Realistic delay |
|---|---|
| Lost ack, lease expiry | seconds |
| Consumer crash and restart | seconds to a minute |
| Rebalance after a deploy | seconds to minutes |
| Retry with exponential backoff ([Lesson 8](../08-retries-backoff-and-dead-letter-queues/)) | minutes to hours |
| **Manual dead-letter queue redrive by an on-call engineer** | **hours to days** |
| A deliberate replay from an offset ([Lesson 5](../05-the-log-offsets-and-replay/)) | anything |

The last three are where people get hurt. A 15-minute dedup TTL is entirely sensible against lost acks and entirely useless against a DLQ redrive at 4 p.m. for messages that failed at 9 a.m. — and the program below charges five customers twice to prove it. When you *do* replay deliberately from an old offset, understand that you are replaying past the window on purpose, and that your idempotency will not save you; that operation needs its own plan.

Two more properties of the dedup store belong in your design doc. **It must be shared by every consumer instance** — a per-process in-memory set deduplicates nothing, because redelivery is precisely the case where a *different* instance picks the message up. That makes it a network dependency on the hot path of every message, with its own latency, availability and failure mode: decide now whether an unreachable dedup store means "process anyway and risk duplicates" or "stop and build backlog". Both are defensible; not having decided is not. And **it is state**, so it needs backups, capacity, expiry monitoring, and a metric counting the duplicates it suppresses — a sudden rise there is often the earliest signal you get that acks are being lost or a consumer is timing out.

### Effects you cannot deduplicate

Everything above assumes the effect is a write to a store you control. Some effects are not.

- **Sending an email or an SMS.** Once it is with the provider it is gone. There is no rollback.
- **Calling a third-party API without an idempotency key.** Their state changed; you cannot inspect or undo it.
- **Printing a letter, dispensing cash, launching a physical process.** Obviously.
- **Publishing to another broker**, which merely moves the problem one hop downstream.

Two mitigations, in order.

**Push idempotency to the boundary.** Most serious APIs accept an idempotency key precisely because their customers have this problem — Stripe's `Idempotency-Key` header is the convention the industry copied, and it is available on essentially every payment provider worth using. Send a key derived from *your* business event and the external system does the deduplication for you. This turns an undeduplicable effect into a deduplicable one, and it is the single highest-value line of code in an integration.

**Where you cannot, arrange the order so the failure is the cheap one, and document the rate.** Put the *record* of having done it in the same transaction as everything else, do the external call last, and accept that a crash between commit and call loses the effect — or reverse the order and accept that it duplicates. Pick which you prefer, write down the expected rate ("approximately one duplicate welcome email per hundred thousand signups"), and make sure the business has agreed to it. A measured, bounded duplicate rate is an engineering result; an unknown one is an incident waiting for a trigger.

The general principle: **choose the failure mode by the cost of the effect.** A duplicate welcome email is an annoyance. A duplicate $90,000 charge is a chargeback, a support case and a compliance conversation. It is entirely reasonable to run at-most-once for the email and pay for full transactional idempotency for the charge — in the same service, in the same handler.

### Producer-side duplicates: the copy your consumer never sees coming

Everything so far has been about the broker-to-consumer hop. Now look upstream, because the same impossibility applies to the **producer-to-broker** hop, and it produces the duplicate that consumer-side dedup is least likely to catch.

The producer publishes. The broker stores the message and sends a confirmation. **The confirmation is lost.** The producer, exactly like the broker in The Problem, cannot distinguish "the publish never landed" from "the publish landed and the confirm died" — so it retries. Now there are two copies on the broker, and they were created before any consumer existed to deduplicate them.

Whether your consumer catches them depends entirely on one decision:

```python
# DEFEATS every dedup mechanism downstream.
for attempt in range(5):
    publish({"message_id": str(uuid.uuid4()), "order": 1042, "amount": 9000})

# WORKS. The id is a property of the business event, not of the transmission.
mid = f"charge:order-1042"          # or a hash of the business key
for attempt in range(5):
    publish({"message_id": mid, "order": 1042, "amount": 9000})
```

The first version generates a **fresh identifier on every retry**, so the two copies are, as far as every downstream component can tell, two unrelated charges. Both are honoured. This is the most common serious bug in this whole area, and it hides well: the consumer is idempotent, the dedup store is transactional, the tests pass — and money still moves twice, because the two messages genuinely have different keys.

The rule, stated so you can quote it in review: **a message id generated per publish attempt is a transmission id, not an idempotency key.** An idempotency key must be a deterministic function of the business event — `charge:order-1042`, or a hash of `(tenant, order_id, operation)` — so that every retry, every restart, and every redeploy computes the same value. If you use a UUID (Universally Unique Identifier, RFC 4122), generate it **once**, when the business event occurs, and persist it with the event so retries can read it back. That is exactly what the transactional outbox in [Lesson 10](../10-dual-write-outbox-and-cdc/) does for you.

Brokers can help, partially. A broker can deduplicate producer retries by having the producer stamp each record with a **producer id and a monotonic sequence number**: a retry carries the same sequence number, and the broker drops it. This is Kafka's idempotent producer. It is real and worth enabling, and it has an honest limit — the producer id is issued **per session**. Restart the process and it gets a new producer id, its sequence resets, and any retry that straddles the restart is indistinguishable from new work. The program below measures exactly that: broker sequence dedup removes 5 of 6 duplicates and the 6th walks straight through.

Consumer-side idempotency keyed on a stable business id covers all of it, which is why it remains the answer even when your broker offers producer dedup.

### Transactional processing: coupling the effect to the offset

The second honest form of "exactly-once" is the atomic-commit approach, and it is worth understanding precisely because it is real and because its scope is narrow.

A stream consumer runs a **read-process-write** cycle: read a message at offset `n`, compute something, write a result, then commit offset `n+1` so a restart does not re-read it. Those last two steps are two separate writes, and a crash between them is the whole problem again in miniature:

- Commit the offset, then write the result → crash in between loses the result. At-most-once.
- Write the result, then commit the offset → crash in between reprocesses. At-least-once.

Unless the result and the offset go into **one transaction**:

```sql
BEGIN;
  INSERT INTO order_totals (order_id, total) VALUES (1042, 9000)
    ON CONFLICT (order_id) DO UPDATE SET total = EXCLUDED.total;
  UPDATE consumer_offsets SET offset = 4711 WHERE consumer = 'totals' AND partition = 3;
COMMIT;
```

Now there is no interval in which one has happened and the other has not. On restart the consumer reads its offset from the same database that holds its output, and the two are guaranteed consistent. This is exactly-once processing, with no dedup store, no TTL, and no window. Note how it *replaces* the broker's offset tracking with your own — the offset became application state precisely so it could join the transaction.

The same trick works when the output is another topic in the same log: Kafka transactions let a producer write result records and consumer offsets in one atomic commit, with `read_committed` consumers refusing to see records from uncommitted transactions. That is why exactly-once in stream processors is a genuine, provable claim.

And it is why it stops at your boundary. The scope condition is exact: **the effect must live in a system that can participate in the transaction** — the same database, or the same log. If the effect is `POST https://api.stripe.com/v1/charges`, no transaction on earth includes it. Stripe cannot roll back because your commit failed. This is the same wall as the dual-write problem in [Lesson 10](../10-dual-write-outbox-and-cdc/), and the answer is the same: keep the atomic part inside one store, and push the boundary crossing behind an idempotency key.

So when a vendor says "exactly-once", the accurate translation is: *exactly-once effect, within the boundary of systems we can transact over, provided you do not step outside it.* That is a genuinely valuable guarantee. It is not the one the phrase implies.

### Delivery semantics are end-to-end, not a broker setting

Last idea, and the one that gets missed in design reviews. A message rarely takes one hop:

```text
mobile client --> API gateway --> orders service --> broker --> payments consumer --> ledger DB
                                                             \-> email consumer --> SMTP provider
```

Each arrow is its own delivery problem with its own semantics, and the end-to-end guarantee is the **weakest link**. The degradation is asymmetric:

- If **any** hop is at-least-once, the whole chain is at-least-once — duplicates propagate forward and there is no hop downstream that un-duplicates them for free.
- If **any** hop is at-most-once, the whole chain can lose — and no amount of at-least-once elsewhere reconstructs a message that no longer exists anywhere.

A retry at the mobile client produces a duplicate that your broker's producer dedup never sees, because it happened two hops upstream. This is the same insight as the availability arithmetic in [Lesson 1](../01-why-async-and-the-cost-of-coupling/): properties of a chain are computed from the whole chain, not from the component you happen to be configuring.

Which yields the practical posture for the rest of your career: **assume at-least-once everywhere, and make the effect idempotent at the point where the effect happens.** Idempotency at the final effect is the only defence that covers duplicates from every source — client retries, producer retries, broker redeliveries, DLQ redrives and deliberate replays alike. Everything else is a partial optimisation on top of it.

## Build It

[`code/delivery_semantics.py`](code/delivery_semantics.py) is a payments pipeline on a virtual clock: a lossy channel with independent forward and return loss probabilities, a broker with leases and redelivery (the queue from [Lesson 3](../03-build-a-message-queue/)), and three consumers running the **same 40 charges** through the **same network**. Standard library only, every RNG seeded, no wall clock — two runs print byte-identical output.

The channel has two independent loss probabilities, because the forward and return paths fail separately — the asymmetry that makes silence ambiguous:

```python
class Channel:
    def deliver_ok(self) -> bool:      # broker -> consumer
        return self.rnd.random() >= self.deliver_loss

    def ack_ok(self) -> bool:          # consumer -> broker
        return self.rnd.random() >= self.ack_loss
```

The broker's redelivery loop is the mechanism from The Problem, and the `redeliver` flag is the *only* difference between at-most-once and at-least-once:

```python
e.attempts += 1
if self.redeliver:
    e.visible_at = now + self.lease_ms   # start the lease; expiry means redeliver
else:
    e.done = True                        # auto-ack: the broker forgets it right now

if not self.channel.deliver_ok():
    self.stats.deliveries_lost += 1
    continue                             # at-most-once: this charge is gone forever

self.stats.delivered += 1
consumer.handle(e.msg, now)

if self.channel.ack_ok():
    e.done = True
else:
    self.stats.acks_lost += 1            # the work WAS done; the lease will fire anyway
```

The idempotent path puts the dedup record and the effect in one function with no yield point, which is the code equivalent of one transaction — the unique constraint is modelled by the `in` test, and there is no window between it and the write:

```python
def process_once(self, key: str, now: int, account: str, amount: int) -> bool:
    """BEGIN; INSERT INTO processed_messages (key); UPDATE balances; COMMIT"""
    self.expire(now)
    if key in self.dedup:                # <- the unique-constraint violation
        return False
    self.dedup[key] = now
    self.charge(account, amount)
    return True
```

The dedup table and the ledger deliberately live in the **same** `Database` object, because that co-location is exactly the precondition that makes the transactional approach possible. Section 3 then breaks the atomicity by hand, driving an explicit A/B interleaving through separate `check` / `act` / `record` steps to show the same store failing when the window is reopened.

Run it:

```console
$ python delivery_semantics.py
== 1. THE INTERLEAVING: two bugs, and no component malfunctions ==

  TRACE A -- ack LAST (at-least-once).  charge:order-1042, 90.00, lease 500 ms
    t=   0 ms  BROKER    deliver charge:order-1042 (attempt 1), lease starts
    t=  12 ms  CONSUMER  received, begins work
    t= 140 ms  CONSUMER  CHARGED 90.00 -> balance 90.00
    t= 141 ms  CONSUMER  sends ack
    t= 141 ms  NETWORK   *** ack dropped in flight ***            <- a packet died
    t= 500 ms  BROKER    lease expired, no ack seen
    t= 500 ms  BROKER    redeliver charge:order-1042 (attempt 2)  <- correct behaviour
    t= 512 ms  CONSUMER  received, begins work
    t= 640 ms  CONSUMER  CHARGED 90.00 -> balance 180.00          <- CHARGED TWICE
    t= 641 ms  CONSUMER  sends ack
    t= 655 ms  BROKER    ack received, message deleted
    result: customer paid 180.00 for a 90.00 order.
    Every log line above reads 'success'. The broker followed its contract,
    the consumer followed its contract, and the customer was charged twice.

  TRACE B -- ack FIRST (at-most-once). The mirror image, same order.
    t=   0 ms  BROKER    deliver charge:order-1042 (attempt 1)
    t=  12 ms  CONSUMER  received
    t=  13 ms  CONSUMER  sends ack BEFORE doing the work
    t=  26 ms  BROKER    ack received, message deleted            <- no copy remains
    t=  30 ms  CONSUMER  process crashes (OOM kill, deploy, node reboot)
    t=  30 ms  CONSUMER  CHARGE 90.00 never runs
    t= 500 ms  BROKER    nothing to redeliver: the queue is empty
    result: customer paid 0.00 for a 90.00 order.
    Silent. No error, no alert, no dead letter. The money simply never moved.

  The ack is the only lever, and it has two positions:
    ack BEFORE the work  ->  you may LOSE the effect,      never duplicate it
    ack AFTER  the work  ->  you may DUPLICATE the effect,  never lose it
  There is no third position. Choosing where to ack is choosing which bug
  you get, not whether you get one.


== 2. THE SAME WORKLOAD, THREE STRATEGIES ==

  40 card charges, one account per customer, 8 customers
  channel: 12% of deliveries lost, 18% of acks lost, lease 500 ms, max 8 attempts
  expected final balance across all accounts: 8,197.00

  strategy                      sent  deliv  ack lost  unique   dup  lost
  -----------------------------------------------------------------------
  at-most-once                    40     36         0      36     0     4
  at-least-once (naive)           52     47         7      40     7     0
  at-least-once + idempotent      52     47         7      40     0     0

  strategy                      final balance     expected        error   verdict
  -------------------------------------------------------------------------------
  at-most-once                       7,509.00     8,197.00      -688.00   UNDERCHARGED
  at-least-once (naive)              9,663.00     8,197.00    +1,466.00   OVERCHARGED
  at-least-once + idempotent         8,197.00     8,197.00            0   CORRECT

  at-most-once   lost 4 charges worth 688.00 — money that was owed and never moved.
  at-least-once  double-charged 7 times, 1,466.00 of other people's money.
  idempotent     saw the SAME 47 deliveries as the naive run (identical),
                 suppressed 7 duplicates, and landed exactly on 8,197.00.
  Nothing about the delivery layer changed. The consumer changed.


== 3. THE ATOMICITY TRAP: check-then-act is itself a race ==

  Two consumer instances get the same message: instance A is still working
  when its lease expires, so the broker hands the message to instance B.
  This is normal, expected, and happens every day at scale.

  (a) CHECK-THEN-ACT   SELECT 1 FROM processed; if absent: UPDATE; INSERT
      A: SELECT 1 FROM processed WHERE key=... -> 0 rows
      B: SELECT 1 FROM processed WHERE key=... -> 0 rows   <- both passed the check
      A: UPDATE balances SET cents = cents + 9000
      B: UPDATE balances SET cents = cents + 9000          <- SECOND CHARGE
      A: INSERT INTO processed (key)
      B: INSERT INTO processed (key)  (already there)
      -> balance 180.00   expected 90.00   DOUBLE CHARGE
      The dedup store was consulted correctly and still failed, because the
      gap between the SELECT and the INSERT is a window another worker fits in.

  (b) TRANSACTIONAL    BEGIN; INSERT INTO processed (key); UPDATE balances; COMMIT
      A: BEGIN; INSERT key -> ok; UPDATE +9000; COMMIT      -> applied=True
      B: BEGIN; INSERT key -> UNIQUE VIOLATION; ROLLBACK    -> applied=False
      -> balance 90.00   expected 90.00   CORRECT
      No check. The unique constraint IS the check, and the database — the one
      component that can actually serialise two writers — enforces it.

  same interleaving, same dedup store, two code shapes: 180.00 vs 90.00


== 4. THE DEDUP WINDOW: a TTL is a correctness boundary ==

  5 charges processed at t=0, then redriven from a dead-letter queue
  at t=+6h after an on-call engineer fixed the downstream bug (lesson 08).
  expected balance: 375.00

  dedup TTL       alive at redrive  reprocessed     balance   expected   verdict
  ------------------------------------------------------------------------------
  15 minutes                0 of 5            5      750.00     375.00   DOUBLE CHARGED
  24 hours                  5 of 5            0      375.00     375.00   CORRECT

  The idempotency is real; the memory of it is not permanent. A dedup store
  with a TTL is only correct while redeliveries arrive inside the window, so
  the window must exceed your worst realistic redelivery delay — and a manual
  DLQ redrive hours later is exactly that worst case.


== 5. PRODUCER-SIDE DUPLICATES: the copy the consumer never sees coming ==

  12 business events, 25% of publish confirms lost.
  The broker STORED every publish; only the confirm went missing. The producer
  therefore retries 6 publishes that had already succeeded. Those duplicates
  now exist on the broker BEFORE any consumer is involved.
  expected balance: 780.00

  producer id strategy                on wire  charged   dup     balance   expected   verdict
  -------------------------------------------------------------------------------------------
  fresh UUID per publish attempt           18       18     6    1,060.00     780.00   OVERCHARGED
  broker (producer_id, seq) dedup          13       13     1      800.00     780.00   OVERCHARGED
  stable business-derived id               18       12     0      780.00     780.00   CORRECT

  A fresh UUID per attempt is not an idempotency key — it is a *transmission*
  id. It changes on the retry, so every downstream dedup mechanism sees two
  unrelated messages and honours both: 1,060.00 charged against 780.00 owed, +280.00.
  Broker sequence dedup catches retries inside one producer session: it removed
  5 of the 6 duplicates. The restart during event 1's retry issued a new
  producer id and reset the sequence, so 1 walked straight through. That is
  Kafka's `enable.idempotence`, and that is its honest scope.
  Only an id derived from the business event survives retries, restarts and
  redeploys — because it was never generated at publish time at all.


== 6. SUMMARY: every strategy, one table ==

  strategy                                deliv  unique   dup  lost     balance   expected
  ========================================================================================
  at-most-once                               36      36     0     4    7,509.00   8,197.00   <-- WRONG
  at-least-once (naive)                      47      40     7     0    9,663.00   8,197.00   <-- WRONG
  at-least-once + idempotent                 47      40     0     0    8,197.00   8,197.00
  idempotent, TTL 15 minutes                 10       5     5     0      750.00     375.00   <-- WRONG
  idempotent, TTL 24 hours                   10       5     0     0      375.00     375.00
  producer: fresh UUID per attempt           18      12     6     0    1,060.00     780.00   <-- WRONG
  producer: broker (pid, seq) dedup          13      12     1     0      800.00     780.00   <-- WRONG
  producer: stable business id               18      12     0     0      780.00     780.00

  3 of 8 configurations produced the correct final balance.
  Every one of them delivered duplicates. Correctness never came from the
  delivery layer — it came from making the duplicate harmless.
```

Read section 2 slowly, because it is the entire lesson in three rows.

**The delivery numbers are worth checking by hand.** At-most-once sent 40 and delivered 36 — 4 died on the forward path with no second copy, so 4 charges worth **$688.00** never happened. At-least-once sent 52: 40 originals, plus 5 forward-path losses re-sent, plus 7 messages whose *acks* were lost. Those 7 were **already processed successfully** when the redelivery arrived, which is why the naive consumer charged 7 cards twice, for **$1,466.00** that was never owed.

**The two at-least-once rows received byte-identical traffic.** Both sent 52, delivered 47, lost 7 acks. The program prints `identical` after checking. The network did not improve, the broker was not reconfigured, no setting was tuned. The idempotent consumer suppressed all 7 duplicates and landed on **8,197.00 exactly** — the expected total, to the paisa. That contrast is the point of the whole lesson: **correctness did not come from the delivery layer, because it cannot.**

**The direction of the two errors matters more than their size.** At-most-once was $688.00 *short*: money owed that never moved, silently, with no error and no dead letter to investigate. At-least-once was $1,466.00 *over*: money taken that was not owed, generating 7 furious customers who will tell you about it within the hour. The second failure is larger and vastly more visible — which is a real argument for at-least-once even before you fix it, because a bug you can see is a bug you will fix.

**Section 3 is the review comment worth internalising.** The same dedup store, the same interleaving, and the same two consumer instances produce **180.00 with a check-then-act** and **90.00 inside a transaction**. Nothing about the store changed. The broken version consults it *correctly* and still double-charges, because between `SELECT` and `INSERT` there is a window and a second worker fits in it. If you take one review reflex from this lesson, take this one: *when you see a dedup check and an effect as separate statements, ask what serialises them.*

**Section 4 prices the honesty requirement.** A 15-minute TTL against a 6-hour DLQ redrive expired **all 5** dedup records before the replay arrived, and all 5 charges were applied a second time: **750.00 against an expected 375.00**. Exactly the same code with a 24-hour TTL kept all 5 records alive and reprocessed **0**. The consumer's idempotency was never in question — its *memory* was. This is why "our consumer is idempotent" is an incomplete statement, and "our consumer is idempotent for redeliveries within 24 hours, which exceeds our maximum DLQ redrive age" is a complete one.

**Section 5 is the bug people ship.** Six lost publish confirms produced 18 wire records for 12 business events. With a fresh UUID per attempt all 18 were charged — **1,060.00 against 780.00 owed, $280.00 over** — despite a fully transactional idempotent consumer downstream. The dedup store worked perfectly and was useless, because the copies genuinely had different keys. Broker-side `(producer_id, sequence)` dedup removed 5 of 6, and the producer restart during event 1's retry reset the sequence, letting **1** through for **800.00**. Only the stable business-derived id landed on **780.00 exactly** — and note it still put 18 records on the wire. It did not prevent the duplicates. It made them recognisable.

**And the summary is deliberately unflattering: 3 of 8.** Five of these eight are things engineers ship believing they are safe. Every row received duplicates; the three correct ones were correct because the duplicate did nothing.

## Use It

You will configure these mechanisms far more often than you implement them. Each fragment below maps to a primitive you just built.

**Kafka's idempotent producer** is the `(producer_id, sequence)` dedup from section 5, at the broker:

```text
enable.idempotence=true      # producer id + per-partition sequence numbers
acks=all                     # required: the leader waits for the ISR
max.in.flight.requests.per.connection=5
retries=2147483647
```

The broker tracks the last sequence number per `(producer id, partition)` and silently drops a retry that repeats one — eliminating duplicates from *producer retries within a session*, and nothing more. On restart the producer gets a new id and the sequence resets, which is the case the program measured. Enable it (it is the default in recent versions and effectively free); do not mistake it for end-to-end deduplication.

**Kafka transactions** are the atomic offset-plus-effect commit:

```text
# producer
transactional.id=payments-totals-v1   # stable across restarts -> fences a zombie producer
# consumer of the results
isolation.level=read_committed        # never see records from an uncommitted transaction
```

```text
producer.beginTransaction();
producer.send(resultRecord);
producer.sendOffsetsToTransaction(offsets, consumerGroupMetadata);  // offsets join the txn
producer.commitTransaction();
```

`sendOffsetsToTransaction` is the important line: the consumer's offsets are written *inside* the producer's transaction, so results and position commit together. Genuine exactly-once — **for Kafka-to-Kafka read-process-write**. The moment your handler calls an external HTTP API, that call is outside the transaction and you are back to idempotency keys.

**SQS FIFO** is the dedup-window problem, sold as a feature, with the window printed on the tin:

```json
{
  "QueueUrl": "https://sqs.ap-south-1.amazonaws.com/123456789012/payments.fifo",
  "MessageBody": "{\"order\":1042,\"amount\":9000}",
  "MessageGroupId": "customer-42",
  "MessageDeduplicationId": "charge:order-1042"
}
```

AWS deduplicates messages with the same `MessageDeduplicationId` for **five minutes**. That is a real, useful, honestly documented guarantee — and it is a five-minute window, so a retry six minutes later is a new message, and a DLQ redrive is far outside it. Note also that `MessageDeduplicationId` must be **your** stable business key: the content-based option hashes the body, which changes if you add a timestamp. This is section 5's lesson, with a vendor's name on it.

**RabbitMQ** splits the two hops explicitly and deduplicates neither:

```python
channel.confirm_delivery()                      # producer hop: publisher confirms
channel.basic_publish(exchange="", routing_key="payments", body=body)

def on_message(ch, method, properties, body):
    process(body)                               # work first...
    ch.basic_ack(delivery_tag=method.delivery_tag)   # ...then ack. At-least-once.

channel.basic_qos(prefetch_count=32)
channel.basic_consume("payments", on_message)   # auto_ack=True would be at-most-once
```

`auto_ack=True` versus acking after `process()` is literally the `redeliver` flag from the Build It, and `basic_nack(requeue=True)` is a manual lease expiry. AMQP (Advanced Message Queuing Protocol) 0-9-1 gives you the delivery mechanics and no deduplication whatsoever — idempotency is entirely your job.

**Stripe-style idempotency keys** push the guarantee across a boundary you do not own:

```bash
curl https://api.stripe.com/v1/payment_intents \
  -H "Idempotency-Key: charge:order-1042" \
  -d amount=9000 -d currency=inr
```

Same key, same response, no second charge — Stripe retains keys for 24 hours. Derive the key from the business event, never from the delivery attempt, and an undeduplicable external effect becomes a deduplicable one. Every payment provider worth integrating offers some version of this; if one does not, that is a procurement conversation.

**And the humblest mechanism, which is also the most reliable:**

```sql
CREATE TABLE payments (
    order_id   bigint PRIMARY KEY,          -- the natural business key
    amount     bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO payments (order_id, amount) VALUES (1042, 9000)
ON CONFLICT (order_id) DO NOTHING;          -- 0 rows affected => already done, just ack
```

No dedup store, no TTL, no window, no extra dependency, no expiry job, and it is enforced by the one component that can actually serialise concurrent writers. When the natural key exists, this beats every other option in this lesson. Reach for a separate dedup table only when it does not.

## Think about it

1. Your consumer processes a message, and *while it is still working*, its lease expires and the broker hands the message to a second instance. Both finish. Walk through what happens under (a) a check-then-act dedup, (b) a single transaction with a unique constraint, and (c) a conditional `UPDATE ... WHERE version = n`. Which of the three would also protect you if the two instances arrived in the *opposite* order — the stale one last?

2. Your dedup TTL is 1 hour. Your dead-letter queue alarm pages the on-call engineer, who investigates and redrives the queue an average of 4 hours later. State the exact bug this produces, then give three different fixes — one that changes the TTL, one that changes the DLQ process, and one that changes neither because it removes the dedup store entirely.

3. A teammate says "we're on Kafka with `enable.idempotence=true` and `isolation.level=read_committed`, so we have exactly-once and don't need idempotency keys." Their consumer charges cards via Stripe. Identify precisely where the guarantee stops, and name the one line of code that fixes it.

4. The measured run showed at-most-once $688.00 *short* and at-least-once $1,466.00 *over*. For each of these four effects — charging a card, sending a marketing email, updating a "last seen" timestamp, decrementing warehouse stock — say which failure you would rather have, and what that implies about where the ack goes. At least one should get a different answer from the others.

5. Your producer generates `str(uuid.uuid4())` as the `message_id` at publish time and retries failed publishes three times. Your consumer is fully transactional and idempotent on that `message_id`. Explain why the system still double-charges, and describe what you would change *without* touching the consumer.

6. You are asked to make "send the shipping confirmation email" exactly-once. Explain why you cannot, what you can offer instead, and what number you would put in the design doc so that the product owner is agreeing to something specific rather than to a hope.

## Key takeaways

- **The acknowledgement is the only lever, and it has two positions.** Ack *before* the work is **at-most-once**: never duplicates, may lose — measured at 4 lost charges, $688.00 that never moved, silently. Ack *after* the work is **at-least-once**: never loses, may duplicate — measured at 7 double charges, $1,466.00 taken that was not owed. There is no ordering that avoids both.
- **Exactly-once *delivery* is impossible, and this is a proof, not a limitation.** The **Two Generals Problem** (Akkoyunlu, Ekanadham & Huber, SOSP 1975): a sender that receives no ack cannot distinguish "message lost" from "ack lost", and no finite protocol fixes it, because the last message of any such protocol can itself be lost. The related **FLP** result (Fischer, Lynch & Paterson, JACM 1985) says the same about consensus under asynchrony. Silence carries no information.
- **Exactly-once *effect* is achievable, and that is what everyone actually wanted.** Every product advertising exactly-once is selling one of two things: at-least-once delivery plus deduplication, or a transaction that atomically couples the offset commit with the effect. Both are real; neither reaches outside the systems it can transact over. Ask "which one, and what is the scope?"
- **Idempotency (`f(f(x)) = f(x)`) is the answer**, in preference order: make the operation **naturally idempotent** (absolute `SET status='shipped'`, never relative `balance = balance + 10`); then an **idempotency key plus a dedup store**; then **conditional writes** (`WHERE version = n`); then **fencing tokens**, which reject stale work as well as duplicate work.
- **Check-then-act is itself a race, and the fix is atomicity, not a bigger lock.** The measured interleaving produced **180.00 with a check-then-act and 90.00 in one transaction** — same store, same messages. Put the dedup record and the effect in one commit, or use a **unique constraint on the natural business key** and catch the violation. Only the database can serialise two writers; a check your code performs outside a transaction is advisory.
- **A dedup TTL is a correctness boundary, not a housekeeping detail.** A 15-minute window against a 6-hour DLQ redrive expired all 5 records and double-charged all 5 customers (750.00 vs 375.00); 24 hours reprocessed none. Size the window against your *worst* redelivery delay — DLQ redrive and deliberate replay, not lost acks — and remember the store must be shared across all instances, which makes it a stateful hot-path dependency with its own availability.
- **A message id generated per publish attempt is a transmission id, not an idempotency key.** Six lost publish confirms produced 18 wire records for 12 events; a fresh UUID per attempt charged all 18 (**1,060.00 vs 780.00**) *despite* a perfect transactional consumer, because the copies genuinely had different keys. Broker `(producer_id, seq)` dedup — Kafka's `enable.idempotence` — removed 5 of 6 and let the one straddling a producer restart through. Only an id derived from the business event landed exactly on 780.00.
- **Some effects cannot be deduplicated** — emails, third-party calls, physical actions. Push idempotency to the boundary where you can (`Idempotency-Key`, `MessageDeduplicationId`), and where you cannot, choose the failure by the cost of the effect and put the expected duplicate rate in writing.
- **Delivery semantics are end-to-end.** A five-hop chain is at-least-once if any hop is, and can lose if any hop is at-most-once. Assume at-least-once everywhere and make the effect idempotent **at the point where the effect happens** — that is the only defence covering client retries, producer retries, redeliveries, redrives and replays alike.

Next: [Ordering, Partition Keys & Parallel Consumers](../07-ordering-partition-keys-and-parallel-consumers/) — you have made duplicates harmless; now find out what happens to *order* the moment you add a second consumer, and why "the queue is FIFO" stops being true at exactly that point.
