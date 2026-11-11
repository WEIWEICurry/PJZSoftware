/** Local, bounded screenshot queue shared by receipt entry and holdings reconciliation. */
export type ScreenshotFile = { id: string; file: File; hash: string };

export async function appendScreenshots(
  existing: ScreenshotFile[],
  files: File[],
) {
  const added: ScreenshotFile[] = [];
  const hashes = new Set(existing.map((item) => item.hash));
  let size = existing.reduce((sum, item) => sum + item.file.size, 0);
  const notices: string[] = [];
  for (const file of files) {
    if (
      existing.length + added.length >= 20 ||
      size + file.size > 40 * 1024 * 1024
    ) {
      notices.push("最多 20 张、累计 40 MB，其余截图未加入。");
      break;
    }
    if (
      !["image/png", "image/jpeg"].includes(file.type) ||
      !file.size ||
      file.size > 5 * 1024 * 1024
    ) {
      notices.push(file.name + "：请选择不超过 5 MB 的 PNG/JPG。");
      continue;
    }
    const digest = await crypto.subtle.digest(
      "SHA-256",
      await file.arrayBuffer(),
    );
    const hash = Array.from(new Uint8Array(digest), (n) =>
      n.toString(16).padStart(2, "0"),
    ).join("");
    if (hashes.has(hash)) {
      notices.push(file.name + "：相同截图已在队列中。");
      continue;
    }
    hashes.add(hash);
    size += file.size;
    added.push({ id: crypto.randomUUID(), hash, file });
  }
  return { added, message: notices.join(" ") };
}
