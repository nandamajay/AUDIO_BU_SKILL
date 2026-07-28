// SPDX-License-Identifier: GPL-2.0-only
/*
 * ABSENT-fixture companion: readable ADAU197x SPI driver whose of_match_table
 * lists adau1977/adau1978 but NOT adau1979. Exercises the CodecDriverProbe
 * ABSENT branch for the adau1979 codec key (file readable via the family
 * candidate list, but no matching .compatible literal present).
 */

static const struct of_device_id adau1977_spi_ids[] = {
	{ .compatible = "adi,adau1977" },
	{ .compatible = "adi,adau1978" },
	{ }
};
MODULE_DEVICE_TABLE(of, adau1977_spi_ids);
