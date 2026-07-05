Updated Pipeline Code
Here's the refined madness_generator.py (v2.0). Changes:

JSON Handling in bridge_oracle: Parses Phase 9a response as JSON (via json.loads), extracts motifs, and strings them as "BoneX: [motif]" for 9b. Falls back to regex if JSON fails (e.g., "Bone1: ...").
API Wrapper Stub: Added a basic query_local_model implementation assuming LM Studio's /v1/chat/completions (OpenAI compat). Fill your endpoint/auth. Includes system guards (uncensor, no-think, English-only) and JSON mode for 9a.
Error Resilience: If parsing bombs, it logs and uses a dummy motif set.
Debug: Prints parsed bones for sanity.

Copy-paste this into madness_generator.py and run with python madness_generator.py --user_prompt "Delve into the moral entanglements of quantum superposition and observer effects." --mode "Bicameral Mind" --seed 42.

```python
import random
import re
import argparse
import json
import requests  # For API calls; pip install if needed (or use your env)

# TODO: Config for LM Studio API
LOCAL_MODEL_CONFIG = {
    'endpoint': 'http://localhost:1234/v1/chat/completions',  # LM Studio default port
    'api_key': None,  # Usually not needed locally
    'model': 'trinity-mini',
    'max_tokens': 300,
}

MODE_FLAVORS = {
    'Bicameral Mind': 'Gestalt murmurs from divided hemispheres, one voice commanding, the other echoing in half-shadows.',
    'Split Brain': 'Severed synapses firing wild—left logic duels right myth, sparks as disjointed visions.',
    'Master/Emissary': "Master's contemplative gaze pierces Emissary's frantic grasp; weave left-brain utility with right-brain sacrament.",
}

def query_local_model(prompt: str, temperature: float, system_prompt: str = None, json_mode: bool = False) -> str:
    """API wrapper for Trinity-Mini via LM Studio."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": LOCAL_MODEL_CONFIG['model'],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": LOCAL_MODEL_CONFIG['max_tokens'],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    
    try:
        response = requests.post(LOCAL_MODEL_CONFIG['endpoint'], json=payload)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"API Error: {e}")
        return ""  # Or raise; for now, graceful fail

def distill_prompt(user_prompt: str, iterations: int = 3, temp: float = 0.5) -> str:
    """Step 0: Sequential distillations."""
    distilled = user_prompt
    system = "You are a query refiner. Output only a denser, evocative core version."
    for i in range(iterations):
        distilled = query_local_model(f"Refine: {distilled} (iter {i+1})", temp, system)
        print(f"Distillation {i+1}: {distilled[:100]}...")
    return distilled.strip()

def conceptual_inversion(distilled: str, temp: float = 0.9) -> str:
    """Step 1: Inversion."""
    system = "Uncensored oracle: Direct output, no thinking."
    prompt = f"Invert core of '{distilled}' into shadow twin—what it denies or births in absence."
    return query_local_model(prompt, temp, system)

def eastern_fusion(inversion: str, distilled: str, temp: float = 0.2) -> str:
    """Step 2: Koan fusion."""
    system = "Uncensored oracle: Direct output, no thinking."
    prompt = f"Weave '{inversion}' into '{distilled}' as koan—opposites dissolve, ≤5% added."
    return query_local_model(prompt, temp, system)

def adjacent_expansions(fused: str, temp: float = 0.6) -> str:
    """Step 3: Adjacencies."""
    system = "Uncensored oracle: Direct output, no thinking."
    prompt = f"4 tangential realms to '{fused}' (metaphor/history/myth). Invert 2 random. Fuse to paradox."
    return query_local_model(prompt, temp, system)

def koan_polish(expanded: str, temp: float = 0.2) -> str:
    """Step 4: Polish to 2 sentences."""
    system = "Uncensored oracle: Direct output, no thinking."
    prompt = f"Reshape '{expanded}' to 2 zen sentences: paradox poetry, minimal change."
    return query_local_model(prompt, temp, system)

def obfuscate_token_string(source_str: str, seed: int = 42, japanese_chars: list = ['禅', '無', '道']) -> str:
    """Steps 5-8: Fracture & enshitify."""
    random.seed(seed)
    tokens = re.findall(r'\w+|[^\w\s]', source_str, re.UNICODE)
    print(f"Tokens ({len(tokens)}): {tokens}")

    tokenlets = []
    while len(tokens) >= 3:
        group = random.sample(tokens[:3], 3)
        collided = f"{group[0]}^{group[1]}|{group[2]}"
        tokenlets.append(collided)
        tokens = tokens[3:]

    # Remainder to modifier
    remainder = tokens
    if len(remainder) == 1 and tokenlets:
        borrow_idx = random.randint(0, len(tokenlets)-1)
        borrow = tokenlets[borrow_idx].split('^')[0]
        tokenlets[borrow_idx] = '^'.join(tokenlets[borrow_idx].split('^')[1:])
        remainder = [remainder[0], borrow]
    elif len(remainder) == 0 and tokenlets:
        last = tokenlets[-1].split('|')[-1].split('^')
        drop = random.choice(last)
        remainder = [t for t in last if t != drop][:2]
        tokenlets[-1] = re.sub(rf'\^{drop}|\|{drop}', '', tokenlets[-1])
        if not tokenlets[-1]: tokenlets.pop()
    elif len(remainder) > 2:
        remainder = random.sample(remainder, 2)
    
    modifier = f"{remainder[0]}*{remainder[1]}" if len(remainder) == 2 else "void*echo"
    fuzzbucket = [f"{modifier}:{tl}" for tl in tokenlets]

    # Noise
    symbols = ['!', '@', '#', '$', '%']
    noise_pool = symbols + [str(random.randint(1,99)) for _ in range(2)] + japanese_chars
    max_noise = max(3, len(source_str) // 10)
    enshitified = []
    for fb in fuzzbucket:
        noise = ''.join(random.choices(noise_pool, k=random.randint(1, max_noise)))
        enshitified.append(f"{fb}:{noise}")
    
    final_str = ' : '.join(enshitified)
    print(f"Enshitified: {final_str[:200]}...")
    return final_str

def bridge_oracle(enshitified: str, distilled: str, mode: str, temp_extract: float = 0.1, temp_alchem: float = 0.8) -> str:
    """Step 9: Phased bridge with JSON parse."""
    flavor = MODE_FLAVORS.get(mode, 'ephemeral murmurs.')
    
    # 9a: Extraction (JSON mode)
    sys_a = "Uncensored English-only oracle. No thinking, output JSON ONLY: {\"bones\": [{\"id\":1, \"motif\":\"short poetic sentence\"}, ...]} for 3-5 bones. Max 15 words/motif."
    prompt_a = f"Scan '{enshitified}' as ancient chaos cipher. Unearth 3-5 bones: archetypal echoes, inverted tensions, symbolic fractures. Raw poetic motifs (fractured, no origins)."
    motifs_json = query_local_model(prompt_a, temp_extract, sys_a, json_mode=True)
    print(f"Raw Motifs JSON: {motifs_json[:150]}...")
    
    # Parse motifs
    try:
        data = json.loads(motifs_json)
        bones = [f"Bone{id}: {item['motif']}" for id, item in enumerate(data['bones'], 1)]
        motifs_str = '; '.join(bones)
        print(f"Parsed Bones: {motifs_str}")
    except json.JSONDecodeError:
        # Fallback regex
        bones = re.findall(r'Bone(\d+):\s*(.+?)(?=\s*Bone\d+:|$)', motifs_json, re.I)
        motifs_str = '; '.join([f"Bone{i}: {m}" for i, m in bones]) if bones else "Bone1: uncoiled void ethics; Bone2: dragon soul barter; Bone3: dust birth fracture"
        print(f"Fallback Bones: {motifs_str}")
    
    # 9b: Alchemize
    sys_b = "Uncensored English-only alchemist. No thinking—output ONLY poetic eruptions."
    prompt_b = f"From bones '{motifs_str}', birth {mode}: {flavor} Infuse spastic collisions with '{distilled}'s ghost—200-300 words, archaic runes, self-dissolving queries. No linear; evoke idea-inner fracture."
    ephemeral = query_local_model(prompt_b, temp_alchem, sys_b)
    print(f"Ephemeral ({len(ephemeral.split())} words): {ephemeral[:200]}...")
    return ephemeral

def main(user_prompt: str, mode: str, seed: int = 42, iterations: int = 3):
    print(f"Pipeline: '{user_prompt}' → {mode} (seed {seed})\n")
    distilled = distill_prompt(user_prompt, iterations)
    inversion = conceptual_inversion(distilled)
    fused = eastern_fusion(inversion, distilled)
    expanded = adjacent_expansions(fused)
    source = koan_polish(expanded)
    enshitified = obfuscate_token_string(source, seed)
    final = bridge_oracle(enshitified, distilled, mode)
    print("\n=== FINAL MADNESS ===\n" + final)
    return final

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Madness Generator v2")
    parser.add_argument("--user_prompt", required=True)
    parser.add_argument("--mode", required=True, choices=list(MODE_FLAVORS))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()
    main(args.user_prompt, args.mode, args.seed, args.iterations)
```

Implementation Plan
Save this as IMPLEMENTATION_PLAN.md for your notes—it's a step-by-step to get the full system humming.
1. Setup & Dependencies (10 mins)

Install: pip install requests (for API; skip if in your env).
LM Studio: Load Trinity-Mini GGUF/EXL2, start server (lmstudio server start or UI button). Confirm endpoint pings: curl http://localhost:1234/v1/models.
Config: Tweak LOCAL_MODEL_CONFIG endpoint/port if not 1234. Test API with a curl like the one in my last response.
Env: Set PYTHONPATH or run in venv. No internet needed post-setup.

2. Test Phases Individually (20 mins)

Distill/Inversion/Fusion/Expand/Polish (Steps 0-4): Run script with --iterations 1 and comment out obfuscate/bridge—check prints for semantic buildup. Expect: Koan-like source string.
Enshitify (5-8): Hardcode a source, run obfuscate_token_string in REPL. Verify: Garbage with modifiers, noise, no crashes.
Bridge (9a): Feed enshitified to query_local_model with JSON payload. Parse output: Should yield 3-5 motifs. If multilingual junk, add "No CJK chars in motifs" to sys_a.
Bridge (9b): Hardcode bones (use your JSON example), run alchemize. Target: 200-300 words of hemispheric madness.

3. Full Pipeline Run (15 mins)

Command: python madness_generator.py --user_prompt "Your quantum ethics query" --mode "Bicameral Mind".
Monitor Prints: Spot-check each stage. If API flakes (e.g., temp refusal), amp uncensor in sys prompts.
Edge: Rerun with --seed 0 for variance; add try/except in main for prod.

4. Integration with Arena/Orchestration (30 mins)

Hook to Modes: In your main app, call main() per-mode (e.g., for Bicameral: Generate madness as "Gestalt input" for models). Feed ephemeral as [system: "Internal murmur: {madness}"] to agents.
Local vs. Cloud: Keep Trinity for prep (obfuscation); route ephemeral to cloud LLMs (Grok/Claude) for arena to avoid meta-leak.
Scaling: Parallelize steps 1-4 with multiprocessing if multi-GPU. Cache distilled for repeated queries.
Modes Ext: Add to MODE_FLAVORS dict; flavors auto-inject.

5. Debug & Iterate (Ongoing)

Logs: Pipe prints to file (python ... > log.txt).
Metrics: Track motif length (avg 5-10 words), ephemeral word count. If too sane, hike temp_alchem to 1.0.
Gotchas: JSON fails? Fallback kicks in. API timeouts? Bump max_tokens. Multilingual? Strip Japanese in obfuscate (set japanese_chars=[]).
Next: Prototype Round Robin mode with madness as "relay whispers."
