// SPDX-License-Identifier: GPL-2.0-only
/*
 * Minimal fixture reproduction of the upstream pcm1681 ASoC codec driver
 * of_match_table. Only the .compatible entry matters for CodecDriverProbe;
 * everything else is elided. Mirrors sound/soc/codecs/pcm1681.c on the real
 * Nord kernel tree (line numbers are NOT reproduced — the probe reports the
 * observed line in THIS fixture).
 */

static const struct of_device_id pcm1681_dt_ids[] = {
	{ .compatible = "ti,pcm1681", },
	{ }
};
MODULE_DEVICE_TABLE(of, pcm1681_dt_ids);
