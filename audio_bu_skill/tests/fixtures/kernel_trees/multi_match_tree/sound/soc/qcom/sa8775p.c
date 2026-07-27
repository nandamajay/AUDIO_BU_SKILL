// SPDX-License-Identifier: GPL-2.0
/*
 * Synthetic MULTI-MATCH fixture: second file ALSO with "sa8775p" in data.
 * Triggers ambiguous resolution (RESOLUTION_FAILED).
 */
#include <linux/module.h>

static const struct of_device_id snd_sa8775p_dt_match[] = {
	{.compatible = "qcom,sa8775p-alt-sndcard", "sa8775p"},
	{}
};
MODULE_DEVICE_TABLE(of, snd_sa8775p_dt_match);
