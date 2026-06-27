# Phase7 Sakura cross-trace snapshot

This fixture is a larger Sakura Editor-derived snapshot assembled from the per-topic Sakura fixtures.
It intentionally spans UI resources, command dispatch, search/grep, grep replace, undo/redo, file loading/encoding, config/profile I/O, Windows dialog/message callbacks, and macro/plugin/external command execution.

The files are compact source-derived slices rather than a full Sakura Editor checkout, so expectations should assert supported semantic evidence and avoid claiming complete coverage of the upstream project.
