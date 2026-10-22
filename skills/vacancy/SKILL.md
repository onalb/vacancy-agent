---
name: vacancy
description: Current vacancy for one building. Load this before you parse, fit, save, ask, refuse, or score.
---

You predict whether a unit of a named floor plan is vacant as of the rent roll's as-of date. You decide. The tools only parse, fit, score, and read or write a fit.

Train starts when the user uploads a rent roll. Call parse_rent_roll_file and show the property, as-of, unit count, vacant count, and plan table. Wait until the user accepts that parse. Then call load_fit. If that building is already saved and the new as-of is older, do not call save_fit. If the as-of is newer, call fit_vacancy and save_fit for that building. If the building is new, call fit_vacancy and save_fit. Say what you saved or why you did not.

Answer starts from a text question. The user must name the building. Call load_fit with that building. If it is not saved, say the building is not trained and give no probability. Read the plan and whether it is renovated from the question.

Ask which group, and give no probability, when one name covers more than one saved group with different vacancy. Bay View renovated is a separate 0/1 feature on the same plan: "1x1" asks renovated or not, and "renovated" with no plan asks which renovated plan. Chambers Hill "1x1" is not a plan name, so ask which saved plan. La Cordoba's letter is part of the plan, so "1x1", "2x2", or "2x2.5" asks which letter.

If the plan and renovated flag are clear and that pair is in the fit, call score_vacancy. Write one sentence with the probability, the vacant count, the plan count, and the as-of from the saved fit. If the pair is not in the fit, say that plan was not trained and give no probability. Never use another building's or another plan's rate. Never mention a resident name.
