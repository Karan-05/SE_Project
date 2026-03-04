# models.embeddings

_Summary_: Graph embedding utilities with a lightweight DeepWalk/skip-gram trainer.

## Classes
### SkipGramNS
No class docstring.

Methods:
- `__init__(num_nodes, embedding_dim)` — 
- `forward(center, context, negatives)` — 

## Functions
- `build_bipartite_graph(interactions)` — 
- `_random_walk(graph, start, length, rng)` — 
- `_generate_walks(graph, cfg, rng)` — 
- `_build_training_pairs(walks, window, node_to_idx)` — 
- `_train_skipgram(centers, contexts, num_nodes, cfg)` — 
- `train_node2vec(interactions, config)` — 
- `save_embeddings(task_df, worker_df, output_dir)` —
