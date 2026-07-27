// SPDX-License-Identifier: GPL-2.0
/*
 * Synthetic ABSENT-tree fixture for test_generation_source_probe.
 * NOT the live checkout. Mirrors the real Nord observation: the driver .c
 * is readable but does NOT list the Nord sound-card compatible, so
 * SourceProbe.driver_match("qcom,nord-iq10-sndcard") → ABSENT.
 */

#include <linux/module.h>

static const struct of_device_id snd_sc8280xp_dt_match[] = {
	{ .compatible = "qcom,sc8280xp-sndcard", .data = "sc8280xp" },
	{ .compatible = "qcom,qcm6490-idp-sndcard", .data = "qcm6490" },
	{}
};
MODULE_DEVICE_TABLE(of, snd_sc8280xp_dt_match);
