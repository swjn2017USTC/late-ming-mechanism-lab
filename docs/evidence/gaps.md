# Evidence gaps

Generated from the registries. A gap is a place where the chain from claim to code is
missing, not a place where the model is wrong.

## Clusters

- **drought_climate**: covered
- **famine**: covered
- **agriculture**: covered
- **population_migration**: covered
- **grain_market_prices**: covered
- **land_debt_elites**: covered
- **taxation_levies**: covered
- **relief**: covered
- **military_finance**: covered
- **rebellion_armed_groups**: covered

## Rules with no evidence behind them

0 declared rule(s) cite no ledger entry and are not declared
exploratory. Each is either a rule waiting for evidence or a rule mislabelled as
theoretically assumed:

- none

## Parameters whose value is still ours

101 of 111 parameters are grade S with no source fixing the
value. Of those, 26 are framed by at least one ledger claim (the record
establishes the mechanism and its order of magnitude) and 75
have no claim attached at all — those are the thinnest places in the model:

- BandParameters: 21 of 21 grade S (16 with no claim attached)
- CropParameters: 1 of 3 grade S (1 with no claim attached)
- EliteParameters: 9 of 9 grade S (2 with no claim attached)
- FiscalParameters: 8 of 9 grade S (4 with no claim attached)
- GovernanceIndicatorParameters: 8 of 8 grade S (8 with no claim attached)
- HistoricalCoreParameters: 8 of 9 grade S (5 with no claim attached)
- HouseholdParameters: 14 of 14 grade S (12 with no claim attached)
- MarketParameters: 8 of 10 grade S (7 with no claim attached)
- MigrationParameters: 7 of 7 grade S (4 with no claim attached)
- MilitaryParameters: 17 of 21 grade S (16 with no claim attached)

## Unverified bibliographic records

7 of 28 source records were recorded but not confirmed
against a locator in this phase. A claim resting on one may not exceed grade C:

- `broadberry-gupta-wang-2024-ming` — National income and agricultural yields, Ming dynasty estimates (dataset)
  - next action: The Cambridge Core chapter record 404s from this environment; a person with a library subscription confirms the chapter and which table the 220 and 256 jin/mu figures come from. The working-paper PDF at the recorded URL was acquired and hashed in V2-P01 (snapshot broadberry-2024-working-paper), so the figures can be traced to a table once the version question is settled.
- `cao-2024-population` — The Population History of China (1368-1953) (modern_scholarship)
  - next action: Brill returns a bot challenge to automated access. A person with a library subscription opens the monograph and confirms chapter 6's Ming-Qing population decline figures.
- `chen-2020-megadrought` — One Drought and One Volcanic Eruption Influenced the History of China: The Late Ming Dynasty Mega-drought (modern_scholarship)
  - next action: Wiley/AGU returns HTTP 403 to this environment. A person with a library subscription opens the article page and confirms the 1637-1643 megadrought claim and the 1641 eruption argument where the ledger attributes them.
- `guo-2001-grain-yields` — 明清时期的粮食生产与农民生活水平 (modern_scholarship)
  - next action: No open locator exists for this chapter. A reader with access to Chinese research libraries confirms 中国社会科学院历史研究所学刊 第一集, pp. 373-396, and reads the yield table the ledger's 0.2-1.0 shi/mu band is attributed to.
- `local-gazetteers` — Various local gazetteers (方志) of Ming provinces and counties (reference_work)
  - next action: This record is a category rather than a titled source, so it cannot be verified as it stands. Replace it with named gazetteers (title, edition, juan) as the acquisition queue is worked; unverified, no claim may rest on it above grade C.
- `ming-shilu` — 明實錄 (Veritable Records of the Ming), Chongzhen reign (primary)
  - next action: Open the Academia Sinica digital edition (mh.sinica.edu.tw/tyml/) from a network that reaches it — the V2-P01 environment could not connect — or a library copy of the Zhonghua Shuju print, and confirm one Chongzhen-reign juan against this record.
- `quan-1991-northern-prices` — 明代北边米粮价格的变动 (modern_scholarship)
  - next action: A reader with access to Chinese research libraries consults the 1991 Daoxiang edition, pp. 653-700, and checks the Yansui series (about 0.2 tael per shi in the mid-fifteenth century; 4 tael per shi in Chongzhen 4) that the grain-price ledger rests on.

## Acquisition queue (human only)

These sources are behind institutional or manual access. **No agent may acquire them**;
the registry records the condition and the locator, and a human decides what to consult:

- `guo-2001-grain-yields` — institution: Chapter in an edited volume; available at Chinese research libraries. No page opened and no file acquired.
- `local-gazetteers` — institution: Local gazetteers held in Chinese provincial and national libraries; not acquired by agent.
- `ming-shilu` — institution: Print edition available in major research libraries; the Academia Sinica digital edition may require institutional access. No individual Chongzhen-reign entry was opened during this phase, and no file was acquired.
- `quan-1991-northern-prices` — institution: Published monograph chapter; available at Chinese research libraries. No page opened and no file acquired.

## Inputs acquired, and inputs still owed

18 snapshot(s) are recorded in `sources/snapshots/`: 17 acquired and hashed,
1 pending. A raw file is never tracked; what the
repository keeps is the record, the derived-output rule and the hash.

| snapshot | source | licence | redistribution | state | next step |
| --- | --- | --- | --- | --- | --- |
| broadberry-2024-working-paper | broadberry-gupta-wang-2024-ming | unknown | unknown | acquired | No yield figure may be published as this paper's until the version question is settled; a derived table may cite the chapter and the working paper as the locator of the figure, and the card that uses it stays grade S or C until the table itself is read. |
| chen-2024-article-pdf | chen-2024-chongzhen | open-attribution | attribution-required | acquired | CC BY 4.0 permits redistribution and adaptation with attribution, so the file could be committed; it is kept local by policy, because the repository publishes derived tables rather than third-party files. |
| chgis-v6-county-points | chgis-v6 | academic-only | prohibited | acquired | The V2 historical core is a derived selection, not a redistribution: node ids, names, date ranges and coordinates for the counties the model uses may be published with the mandatory citation and a statement of what was changed, omitted and re-projected. |
| chgis-v6-county-readme | chgis-v6 | academic-only | prohibited | acquired | May be quoted to describe the layer variant; not republished. |
| chgis-v6-courier-readme | chgis-v6 | academic-only | prohibited | acquired | May be quoted; not republished. |
| chgis-v6-courier-routes | chgis-v6 | academic-only | prohibited | acquired | Derived values (link existence, distances, station counts) may be published with the mandatory citation and a description of the changes; the layer itself is not republished. |
| chgis-v6-courier-stations | chgis-v6 | academic-only | prohibited | acquired | Derived values (link existence, distances, station counts) may be published with the mandatory citation and a description of the changes; the layer itself is not republished. |
| chgis-v6-data-dictionary | chgis-v6 | academic-only | prohibited | acquired | Field names and their meanings may be restated in a derived schema with the mandatory citation; the dictionary tables are not republished. |
| chgis-v6-dictionary-readme | chgis-v6 | academic-only | prohibited | acquired | May be quoted to describe the dictionary's scope; not republished. |
| chgis-v6-eula | chgis-v6 | academic-only | prohibited | acquired | The licence terms themselves may be quoted. |
| chgis-v6-periods | chgis-v6 | academic-only | prohibited | acquired | Period and reign boundaries may be restated as dates in a derived table with the mandatory citation; the tables are not republished. |
| chgis-v6-readme | chgis-v6 | academic-only | prohibited | acquired | Facts about the dataset (layers, date coverage, field semantics) may be restated with the mandatory citation; the document itself is not republished. |
| reaches-noaa-codes-haz | reaches-noaa | unknown | unknown | acquired | The coding guide may be quoted to decode event codes; it is not republished. |
| reaches-noaa-codes-met | reaches-noaa | unknown | unknown | acquired | The coding guide may be quoted to decode event codes; it is not republished. |
| reaches-noaa-codes-other | reaches-noaa | unknown | unknown | acquired | The coding guide may be quoted to decode event codes; it is not republished. |
| reaches-noaa-data-v31 | reaches-noaa | unknown | unknown | acquired | Same as the readme: aggregated, attributed derived series may be published; the record file and any extract of individual records stay local until the licence question is answered. |
| reaches-noaa-readme | reaches-noaa | unknown | unknown | acquired | Aggregated derived series - for example events per year for Shaanxi and Henan, or a drought and famine year index - may be published with the NOAA landing page and the Wang et al. |
| reaches-sinica-full-database | reaches-noaa | restricted | unknown | human | A person with an Academia Sinica account (or the account application) decides whether to request the full release. No agent downloads from it or applies for an account on the project's behalf. |

## Licence questions that are still open

An unresolved licence is recorded as a question, not as permission. Until an answer is on
file, the rule is: aggregated derived output may be published with attribution, the file
and any transcription of it may not.

- **broadberry-2024-working-paper** (unknown): Does the working paper's own availability permit citation and derived use, and is it the version the chapter's yield figures come from? The published chapter's terms govern the published figures either way.
- **reaches-noaa-codes-haz** (unknown): May the coding guide be redistributed, and does its use carry the same condition as the records it describes? Ask NOAA/WDS and the Academia Sinica team.
- **reaches-noaa-codes-met** (unknown): May the coding guide be redistributed, and does its use carry the same condition as the records it describes? Ask NOAA/WDS and the Academia Sinica team.
- **reaches-noaa-codes-other** (unknown): May the coding guide be redistributed, and does its use carry the same condition as the records it describes? Ask NOAA/WDS and the Academia Sinica team.
- **reaches-noaa-data-v31** (unknown): May a third party republish this file, or extracts from it, given that the underlying text rights belong to the Compendium and the Sinica release requires an account application?
- **reaches-noaa-readme** (unknown): What terms govern redistribution of the NOAA-hosted REACHES file, given that the Wang et al. 2018 data descriptor says the rights in the original quoted records belong to the Compendium and that the complete database is released on application at reaches.rcec.sinica.edu.tw? Ask NOAA/WDS and the Academia Sinica REACHES team before republishing any part of the file.
- **reaches-sinica-full-database** (restricted): What do the account terms permit a research project to do with the release, and is the account-holder's use compatible with publishing derived tables?

## Structural gaps this phase did not close

- No source in the registry measures a 1625-1644 Shaanxi-Henan quantity directly at the
  resolution the model uses (county-month). Where a claim carries a magnitude, it is a
  regional or annual figure being used at a finer resolution, and the card says so.
- The registry holds no archival material: county-level quota books, relief registers and
  garrison payrolls are named as gaps rather than approximated.
- Nothing here calibrates anything. Every pattern carries a calibration role, and the
  hold-out patterns are marked so a later phase cannot silently fit them.
