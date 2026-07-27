// SPDX-License-Identifier: GPL-2.0
/*
 * Synthetic NO-FAMILY fixture: has a driver file with MODULE_DEVICE_TABLE
 * but NO match-table entry with "sa8775p" in .data.
 * Triggers RESOLUTION_FAILED (zero matches).
 */
#include <linux/module.h>

static const struct of_device_id snd_x1e80100_dt_match[] = {
	{.compatible = "qcom,x1e80100-sndcard", "x1e80100"},
	{.compatible = "qcom,glymur-sndcard", "glymur"},
	{}
};
MODULE_DEVICE_TABLE(of, snd_x1e80100_dt_match);
