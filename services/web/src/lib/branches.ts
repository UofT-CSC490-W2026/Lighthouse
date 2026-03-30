export function parseBranchInput(value: string): string[] {
  const seen = new Set<string>();
  const branches: string[] = [];

  for (const segment of value.split(",")) {
    const branch = segment.trim();
    if (!branch || seen.has(branch)) {
      continue;
    }
    seen.add(branch);
    branches.push(branch);
  }

  return branches;
}
