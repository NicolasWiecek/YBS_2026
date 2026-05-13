# Retirement Wealth Gap Analysis: Method Note

## Original claim

Descriptive analysis of wealth levels and wealth gaps between owner households and renter households for cohorts of households around retirement age (65-74) across several rounds of the Office for National Statistics (ONS) Wealth and Assets Survey (WAS), to understand trends and changes over time and to assess how far home ownership is associated with wealth gaps at retirement age.

## Data sources used

- ONS Wealth and Assets Survey household data files for rounds 5 to 8:
  - `was_round_5_hhold.tab`
  - `was_round_6_hhold.tab`
  - `was_round_7_hhold.tab`
  - `was_round_8_hhold.tab`
- ONS Wealth and Assets Survey person data files for rounds 5 to 8:
  - `was_round_5_person.tab`
  - `was_round_6_person.tab`
  - `was_round_7_person.tab`
  - `was_round_8_person.tab`
- CPI/CPIH inflation index file used to express rounds 5 to 7 in March 2022 prices:
  - `CPI_Inflation.csv`
- ONS published round 8 wealth methodology and bulletin figures were used as an external validation point for the treatment of private pension wealth in round 8.

## Method step by step

1. The structure of each WAS household and person file was first checked to identify the round-specific names for the case identifier, household cross-sectional weight, tenure variable, household wealth aggregates, and HRP age variable.

2. For each survey round, the household file and person file were linked using the round-specific case identifier so that the household-level data could be combined with person-level HRP information.

3. The household reference person (HRP) was identified in the person file using the round-specific HRP flag, and the HRP age-band variable was extracted for use in cohort selection.

4. The analytic sample for each round was restricted to households where the HRP was aged 65 to 74, using the WAS age-band coding for that round.

5. Current housing tenure was derived from the round-specific `ten1` tenure classification. Households were grouped into:
   - owners: outright owners and owners with a mortgage or loan
   - renters: private renters and social renters

6. Household wealth measures were extracted for each round. These included:
   - total household wealth
   - total household wealth excluding private pension wealth
   - property wealth
   - financial wealth
   - private pension wealth
   - physical wealth

7. For rounds 5 to 7, household total wealth and component wealth measures were taken directly from the standard household-level WAS aggregate variables.

8. For round 8, the total wealth measure used for any analysis including private pension wealth was adjusted to align with the updated ONS round 8 pension methodology. This was done by replacing the old pension component within the legacy total wealth aggregate with the updated round 8 household pension aggregate. This step was necessary because the published ONS round 8 total wealth estimates include the revised pension method, whereas measures excluding private pension wealth are unaffected by that update.

9. Survey-weighted descriptive statistics were then calculated using the round-specific household cross-sectional weight. For each round, this included:
   - overall median household wealth for the full round sample
   - overall median household wealth excluding private pension wealth for the full round sample
   - weighted mean and weighted median wealth for owners and renters within the 65-74 cohort
   - separate owner-renter results for total wealth, wealth excluding private pension wealth, and each of the four wealth components

10. Owner-renter wealth gaps were summarised in two ways for each measure:
   - absolute gap in pounds
   - owner-to-renter ratio

11. Distributional analysis was undertaken within each round for the 65-74 cohort by producing:
   - kernel density plots for owners and renters
   - weighted wealth decile charts for owners and renters

12. A further low-wealth indicator was calculated for renters by estimating the share of renter households with zero or near-zero private wealth, where private wealth was defined as financial wealth plus private pension wealth and near-zero was defined as £1,000 or less.

13. To support cross-round comparison, both nominal and inflation-adjusted estimates were produced. Rounds 5 to 7 were rebased into March 2022 prices using inflation indices for March of each round’s end year:
   - round 5 rebased from March 2016
   - round 6 rebased from March 2018
   - round 7 rebased from March 2020
   - round 8 left unchanged because values are already in March 2022 prices

14. Final outputs were exported as CSV tables and a combined Excel workbook containing the round-by-round descriptive statistics, owner-renter gap measures, renter low-private-wealth shares, and nominal versus real-terms comparison tables.
