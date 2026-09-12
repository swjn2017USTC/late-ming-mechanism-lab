# ADR 0001 — Space as administrative seats with approximate catchments

Status: accepted
Date: 2026-09-12
Phase: P02 (Historical Space / Time / Climate)
Supersedes: —

## Context

The model needs places. It has to say where a climate anomaly falls, how far grain can move,
where a household can migrate, and how long a force takes to march. The core space is
Shaanxi and Henan between 1625 and 1644, with Shanxi, Huguang, Sichuan and Beizhili only as
boundary connections.

The options available for representing that space are unequal in what they silently claim:

- **Digitized county polygons.** Modern or reconstructed boundary layers carry surveyed lines
  that did not exist for the period. Ming county jurisdiction was a bundle of obligations —
  tax quota, corvée, litigation, relief — with enclaves, exclaves and adjustments across the
  window, and it was not a surveyed border. Rendering such a jurisdiction as a polygon
  produces precise-looking lines with no evidence behind them, and every downstream number
  (area, density, "share of the region affected") inherits that false precision.
- **A raster or grid.** A cell size has no historical justification in this setting, and grid
  cells have no jurisdiction. Fiscal, relief and judicial questions in this model are phrased
  in county units, which a grid dissolves.
- **A single county-adjacency graph.** Loses exactly the distinction the model exists to
  study: between places, trade cost, migration cost and military cost genuinely differ, and a
  single weight would average them into a number that answers no question.
- **Least-cost surfaces over terrain.** Requires a terrain and transport model we do not have,
  and it makes the actual structure (which links exist at all) implicit rather than declared.

The spatial questions in scope are relational — how far, at what cost, at what risk can
something move from here to there — not territorial. Area and border effects are not part of
any mechanism in P00–P14 as planned.

## Decision

1. **Space is a set of nodes.** A node is an administrative seat together with its
   approximate catchment, where the catchment is expressed by the node's links and its
   agrarian zone. No node stores a polygon, an area, or a border.
2. **Coordinates are optional and sourced.** A node may carry a single point with a declared
   precision and uncertainty radius, graded `A`–`D`. An assumed point is rejected in code, not
   merely discouraged: if the point is not sourced, the node has no coordinates.
3. **Quantities live on edges and carry their meaning.** Every edge stores `distance_km`,
   `cost`, `capacity` and `risk`, with a per-graph semantics record stating what cost and
   capacity mean. Distance belongs to the pair of places and must agree across graphs; cost
   belongs to the graph and may differ.
4. **Three separate graphs.** `G_trade`, `G_migration`, `G_military` are built separately from
   the same dataset, each declaring which boundary roles it may use.
5. **Environments are not jurisdictions.** Agrarian zones (loess dryland, north China plain)
   carry cropping season and anomaly sensitivity. They are calibrated environments, separate
   from province identity, so a zone can be re-sourced without touching administrative
   geography.
6. **Scale by adding nodes.** A regional dataset of 50–100 nodes uses the same schema and the
   same validation as the five-node toy fixture; nothing in the representation assumes the dev
   scale.

## Consequences

Positive:

- Uncertainty is explicit at the level where it exists: a node either has a sourced point or
  it does not; every distance and cost is a graded value that can be replaced by a better one.
- The representation does not silently answer questions it cannot support. Reports are phrased
  per node or per catchment ("N of M nodes"), never in area or density.
- The three graphs make the model state which kind of movement it means, which is a
  precondition for testing trade-versus-military-versus-migration mechanisms separately.
- Sourced geography enters through one adapter, so a later dataset cannot smuggle in
  unprovenanced values.

Negative / accepted costs:

- No area, no population density, no border effects, no intra-county space. Questions about
  spatial incidence *inside* a county cannot be asked of this model.
- Movement happens only along declared links, so route choice and unknown corridors are
  approximated by the topology we declare — which is itself a graded modelling choice.
- Catchments are conceptual, so catchment-level quantities (population, grain stock) will
  have to be attached to nodes in later phases without any area-based denominator.
- Comparing modelled node counts to historical county counts is not a validation of the
  representation; it is a statement about how many nodes were declared.

## Rejected alternatives, recorded

| Alternative | Why rejected |
| --- | --- |
| Digitized county polygons | Claims surveyed borders the period did not have; false precision spreads into area-based results |
| Raster / grid | Arbitrary cell size; dissolves the jurisdiction that the fiscal and relief mechanisms are phrased in |
| One adjacency graph | Collapses trade, migration and military costs into one number, destroying the mechanism distinction |
| Least-cost terrain surfaces | Requires an unavailable terrain/transport model and hides which links exist |

## Revisit conditions

Revisit if a mechanism genuinely needs area (for example area-denominated relief or
cultivation), or if a sourced jurisdiction geometry with per-polygon uncertainty and a
documented reconstruction method becomes available. In either case the polygon layer would be
added *alongside* nodes, as a separate graded input for spatial joins, never as a silent
replacement for node-and-catchment space.
