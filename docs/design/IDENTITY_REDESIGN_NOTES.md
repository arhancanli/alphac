# Identity redesign notes: three families that mis-specified their population

**Status: DRAFT. Nothing here is registered.** No hypothesis identity, no threshold, no universe is
fixed by this document. Registering any of it spends a trial from a budget that belongs to the
owner. What follows is the analysis that must come *before* a pre-registration, written down so
that the pre-registration, when it happens, is written against evidence rather than against memory.

*Drafted 2026-08-22. 0 trials: everything measured here is filing metadata and document language on
frozen artifacts, and no return data was opened.*

---

## Why these three, and what they have in common

Three families sat one gate short of clearing feasibility. The natural reading of "one gate away"
is that the parser needs work. It was checked, and for all three the reading was wrong:

| family | gate | measured | what a perfect detector reaches |
|---|---|---|---|
| `spin_off_dislocation` | pro-rata distribution language ≥ 0.30 | 0.1633 | **0.1122** |
| `customer_supplier_propagation` | named-customer rate ≥ 0.50 | 0.3533 | **0.3714** |
| `merger_arbitrage` | prior Item 1.01 8-K ≥ 0.80 | 0.6702 | not a detector problem at all |

Two ask for language the filings do not contain at the assumed rate. The third applies one
threshold across two populations with different filing obligations. None is closed by extraction
work, and the temptation in all three cases is identical and must be named: widen the pattern, or
lower the threshold, until the number clears. That is tuning a measurement to agree with a target,
and it is the one move that would destroy the only thing this programme has.

**The common error is sharper than "the threshold was too high", and it is the same error three
times.** Each protocol specified a *language* test where the identity needed a *structural* fact —
a form type, a timestamp, or a counterparty named on a contract. Narrative prose is the least
reliable carrier of any of those. An issuer writes the narrative; the structure is imposed on them.

Each note below therefore names the document that carries the evidence **before** it says anything
about a threshold, and none of them proposes a threshold at all. That ordering is the point.

---

## Note 1 — `spin_off_dislocation`

### What failed

The protocol looked for pro-rata distribution language in the **initial Form 10**. Across 98 frozen,
hash-verified filings, only 11 contain a pro-rata token in any written form (11.2%) and only 5 have
one near a distribution reference (5.1%), against a gate of 30%. The single false negative reviewed
by eye was a preemptive-rights boilerplate use — a correct negative for the intended meaning, not a
miss.

The shipped detector *overstated* the rate it published: its second alternative matched
`distribut…` followed by `holders of` with no pro-rata text required, so a field named
`pro_rata_distribution_language` fired on six documents that never say pro rata. The gate fails
either way and it fails harder than the record showed.

### Why the document cannot carry it

An initial Form 10 is a **registration statement**. It registers a class of securities and describes
the business being separated. The distribution mechanics — ratio, record date, when-issued
trading — are not settled when it is filed, which is why the information statement attached to an
initial Form 10 routinely carries `[•]` where the ratio will go. The protocol asked a document to
state a fact that did not exist on the day it was written.

### The document that does carry it

**The form type itself.** A Form 10-12B is filed to register a class of securities being
distributed to shareholders. The *act of filing one* declares the event; no sentence inside it has
to. That is metadata in the EDGAR master index, needs no parsing, and cannot be written around.

Measured against the sixty-four quarterly master indexes this repo already holds:

```
2010  19 initial / 64 amendments      2018  25 / 53
2011  27 / 67                          2019  36 / 42
2012  22 / 66                          2020  16 / 19
2013  31 / 70                          2021  20 / 33
2014  38 / 150                         2022  20 / 45
2015  45 / 138                         2023  19 / 46
2016  33 / 151                         2024  17 / 33
2017  10 / 38                          2025   8 / 26
```

**386 initial Form 10-12B filings over 2010–2025, a mean of 24.1 a year.** The universe the original
protocol was trying to rediscover by reading prose was declared by the form type all along.

Two structural facts follow, and one of them is unwelcome:

- The **announcement timestamp** is the EDGAR acceptance time of the first 10-12B for that
  registrant. Metadata, no look-ahead, no parsing.
- **386 events over sixteen years is thin.** Whatever a redesigned identity claims will be bounded
  by that count, and the bound belongs in the pre-registration rather than in a footnote after a
  disappointing result.

### The route that was checked and does not work

The obvious alternative was to take the event universe from the corporate-action feed this repo
already holds. It was checked rather than assumed: sampling 600 instruments, the lake carries
exactly two action types, `dividend` and `split`. **There is no spin-off or distribution action
type in it.** The structured route is the filing index, not the corporate-action record.

### What a corrected identity would look like

An event study keyed on the *filing* rather than on the *language*: universe = registrants with an
initial Form 10-12B in the index; announcement = that filing's acceptance timestamp; the parent's
completion 8-K or the price record supplies the distribution date if the identity needs it.

The whole extraction step leaves the critical path. The redesign's first question is therefore not
"can we parse it?" but "**is 24 events a year enough to say anything?**" — and that question must be
answered, in the pre-registration, before the identity is registered.

---

## Note 2 — `customer_supplier_propagation`

### What failed

The gate asked that at least 50% of documents disclosing a customer concentration **name** the
customer. Measured across 300 documents: 35.3% published, and 37.1% among the 280 that genuinely
carry concentration language. A perfect detector reaches 37.1% against a gate of 50%.

A hypothesis was refuted on the way and is recorded because it was wrong: reading five window
excerpts by eye suggested the denominator was padded with documents disclosing no concentration at
all. Measured across all 300, 93.3% do carry real concentration language. Correcting the denominator
moved the rate about two points against a fifteen-point shortfall. Five excerpts were an
unrepresentative sample.

### Why the document cannot carry it

The disclosure obligation is to report the **concentration**, not the counterparty. An issuer must
tell you that one customer is a material share of revenue; nothing requires them to tell you
which one, and most do not. The gate asked the narrative for something the rule that produces the narrative never
required.

### The document that does carry it

**The contract, not the discussion of it.** A supply or distribution agreement names its
counterparty on its face and is filed as a material-contract exhibit. Two structural surfaces
follow, both metadata rather than prose:

- **Exhibit descriptions in the filing index.** A material contract is listed with a description
  that ordinarily names the parties. This is a short, formulaic field, not narrative.
- **Item 1.01 8-Ks** on entry into a material definitive agreement, which are dated and carry the
  agreement as an exhibit.

The relationship also appears from the other side: a large customer's own filings and its exhibit
list name suppliers more often than a supplier's narrative names customers, because the contract is
filed by whichever party has the disclosure obligation.

### What is NOT known, and must be measured before anything is registered

**The naming rate in exhibit descriptions has not been measured.** It could be higher than 37.1%
or lower. Nothing in this note licenses an assumption about it, and a redesign that carried over
the 50% threshold on the hope that a different surface clears it would repeat the original error
with a new document.

The first step of a redesign is therefore a **document-schema audit of exhibit descriptions** —
the same shape of measurement that produced the 37.1% figure — reporting what fraction of
concentration-disclosing issuers file a contract whose description names the counterparty. Only
after that number exists can a threshold be set, and it must be set *before* the identity is
registered rather than chosen to accommodate the result.

### What a corrected identity would look like

Keyed on the pair `(issuer, named counterparty)` extracted from **contract metadata**, with the
narrative concentration disclosure used only for the materiality test it is actually required to
make. The narrative says *how much*; the contract says *who*. The original protocol asked one
document to do both.

---

## Note 3 — `merger_arbitrage`

### What failed

Nothing, in the extraction sense. The gate required a prior Item 1.01 8-K on at least 80% of deal
anchors and measured 67.0%. Split by form type:

| form | anchors | prior Item 1.01 8-K rate | clears 0.80 |
|---|---|---|---|
| `SC 14D9` | 442 | **0.8665** | yes |
| `DEFM14A` | 1523 | **0.6133** | no |

A tender offer's SC 14D9 follows a contemporaneous merger agreement, so the prior 8-K is nearly
always there. A definitive merger proxy can be filed long after the agreement, by issuers who
announced it another way. **The blended figure describes neither population.**

`SC TO-T` appears in the filing counts and not in the anchor timeline. That is correct and was
checked rather than assumed: it is the bidder's filing, not the target's.

### ⚠️ What this is not

**It is not permission to narrow the universe to tender offers.** Restricting to the population
that was observed to pass is selection, and the 0.8665 is now in-sample for that decision and
cannot serve as its evidence. A tender-offer-scoped identity is a legitimate redesign and it needs
its own pre-registration, with threshold and universe fixed before anything is measured again — on
a sample disjoint from the one that produced 0.8665, or the same number will be doing double duty
as both the reason for the choice and the proof that it was right.

### The specification error underneath

The gate tested for the **presence of a particular document**. What the identity needs is a
**clean announcement timestamp**. Those are not the same requirement, and several documents supply
the second: the Item 1.01 8-K, the preliminary proxy, the merger agreement exhibit, the tender
offer filings. Requiring one specific form is a specification error dressed as a data-quality gate —
it fails on deals that are perfectly well documented in a different order.

### What a corrected identity would look like

Two changes, and the second matters more than the first.

1. **Announcement timestamp from a declared set of forms**, taken as the earliest EDGAR acceptance
   among them, rather than from one mandatory form. The set is fixed in the pre-registration; the
   rule is metadata-only and has no look-ahead.
2. **Deal structure declared as a stratum up front, and reported separately.** We now know the
   populations have different filing obligations. Any redesign that blends them again is
   reintroducing the defect on purpose, and any redesign that silently keeps only the convenient
   stratum is doing something worse. Both strata get published, whatever they say.

---

## What the three notes share, restated because it is the transferable part

Every one of these protocols asked prose to certify a fact that a structure already carried:

- a **form type** declares a spin-off; a sentence inside the filing need not.
- a **contract** names a counterparty; the narrative that discusses it is not required to.
- an **acceptance timestamp** dates an announcement; no single form is required to exist.

The general rule this earns, and it is worth more than any of the three families: **when a gate
measures a rate of language, check first whether the fact is available as structure.** Language
rates are properties of what issuers chose to write. Structure is a property of what they were
required to file, and it does not move when a drafting convention changes.

None of that is evidence that any of these three families has an edge. It is only evidence about
where their evidence would live, which is the question that has to be settled before the expensive
one is asked.
