// SPDX-License-Identifier: GPL-2.0-only
/*
 * ABSENT-fixture: this pcm1681.c is readable but its of_match_table carries NO
 * "ti,pcm1681" compatible (a wrong/placeholder entry stands in). Exercises the
 * CodecDriverProbe ABSENT branch → codec_stub falls back to the hardcoded
 * _NORD_CODECS value, marked NOT kernel-attested. Models a half-written codec
 * driver whose match table has not yet been populated for this part.
 */

static const struct of_device_id pcm1681_dt_ids[] = {
	{ .compatible = "ti,pcm1690", },
	{ }
};
MODULE_DEVICE_TABLE(of, pcm1681_dt_ids);
