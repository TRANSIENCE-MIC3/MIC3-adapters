# © 2026 Wuppertal Institut für Klima, Umwelt, Energie gGmbH
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# remindmfa_to_eumfa_fixed.R
#
# Fixed version of remindmfa_to_eumfa.R. Changes compared to the original:
#   1. FIX: Semi-finished product (IP) trade is now disaggregated correctly.
#      The original applied the sector share (FinalDemand_shares_agg) and then a product
#      share that is relative to the sector GROUP (FinalDemand_shares), which counted the
#      sector share twice for grouped sectors (steel: Automotive/Other Transport,
#      Miscellaneous/Metalware/Domestic appliances) and lost ~14% of the REMIND total.
#      Step 2 now uses the product share within the SECTOR (share_in_sector).
#      Goods trade is unchanged (group-level shares are correct there).
#   2. RStudio-specific code (rstudioapi / setwd) removed. The script can be run with
#      `Rscript remindmfa_to_eumfa_fixed.R` from any directory: it changes into its own
#      folder (MIC3_run_1) if started with Rscript, otherwise it uses the current
#      working directory, which must then be MIC3_run_1.
#   3. NEW: optional unit conversion of the REMIND-MFA trade values. REMIND-MFA trade is assumed
#      to be in t while the EU-MFA steel model works in kt, so use REMIND_UNIT_FACTOR=0.001.


library(yaml)
library(dplyr)
library(tidyr)
library(readr)
library(purrr)

# Set working directory to the folder of this script when run via Rscript
script_arg <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
if (length(script_arg) > 0) {
  setwd(dirname(normalizePath(sub("^--file=", "", script_arg[1]))))
}
cat(sprintf("Working directory: %s\n", getwd()))

models <- c("steel", "plastics")

# Unit conversion applied to all REMIND-MFA trade values (see header)
remind_unit_factor <- 1e-3
if (is.na(remind_unit_factor)) stop("REMIND_UNIT_FACTOR must be numeric")
cat(sprintf("REMIND unit factor: %g\n", remind_unit_factor))

# -----------------------------------------------------------------------------
# STEP 1: Build sector and product shares from EU-MFA data
# -----------------------------------------------------------------------------

# Function to compute shares for a given material folder
process_shares <- function(folder_path, is_steel = TRUE) {

  # File paths
  input_file      <- file.path(folder_path, "FinalDemand_past.csv")
  shares_file     <- file.path(folder_path, "FinalDemand_shares.csv")
  shares_agg_file <- file.path(folder_path, "FinalDemand_shares_agg.csv")

  if (!file.exists(input_file)) {
    warning(sprintf("File not found: %s", input_file))
    return(NULL)
  }

  # Read input CSV
  df <- read_csv(input_file, show_col_types = FALSE)

  # ---------------------------------------------------------------------------
  # 1. Product / Polymer Shares (FinalDemand_shares.csv)
  # ---------------------------------------------------------------------------
  # Grouping dimensions:
  # - Steel: region, time, sector_group, intermediate, element
  #   -> `share`: share of each sector/product within its sector GROUP
  #      (used for goods trade, where the REMIND value is given per group)
  #   -> `share_in_sector`: share of each product within its SECTOR
  #      (used for IP trade, after splitting the REMIND total by sector)
  # - Plastics: region, time, sector, element (sector group = sector)

  df <-  if (is_steel) {
    df %>%
    mutate(
      sector_group = case_when(
        sector %in% c("Automotive", "Other Transport") ~ "Transport Total",
        sector %in% c("Miscellaneous", "Metalware", "Domestic appliances") ~ "Products Total",
        TRUE ~ sector # Keep all other sectors unchanged
      )
    )
  } else {
    df %>%
    mutate(
      sector_group = case_when(
        TRUE ~ sector # Keep all other sectors unchanged
      )
    )
  }

  group_dims <- if (is_steel) {
    c("region", "time", "sector_group", "intermediate", "element")
  } else {
    c("region", "time", "sector", "element")
  }

  # Dimensions defining one sector (used for the product share within a sector).
  # Summed over all remaining dimensions (e.g. intermediate, product/polymer), so that
  # it matches the sector totals used in FinalDemand_shares_agg.csv.
  sector_dims <- c("region", "time", "sector", "element")

  df_shares <- df %>%
    group_by(across(all_of(group_dims))) %>%
    mutate(
      total_group_val = sum(value, na.rm = TRUE),
      # Calculate share (avoiding division by 0)
      share = if_else(total_group_val == 0, 0, value / total_group_val)
    ) %>%
    ungroup() %>%
    group_by(across(all_of(sector_dims))) %>%
    mutate(
      total_sector_val = sum(value, na.rm = TRUE),
      share_in_sector = if_else(total_sector_val == 0, 0, value / total_sector_val)
    ) %>%
    ungroup() %>%
    select(-total_group_val, -total_sector_val, -sector_group) # Remove helper columns

  write_csv(df_shares, shares_file)
  cat(sprintf("Saved product/polymer shares to: %s\n", shares_file))

  # ---------------------------------------------------------------------------
  # 2. Aggregated Sector Shares (FinalDemand_shares_agg.csv)
  # ---------------------------------------------------------------------------
  # Aggregate total demand per region, year (time), element, and sector
  agg_dims <- if ("element" %in% names(df)) c("region", "time", "element") else c("region", "time")

  df_shares_agg <- df %>%
    group_by(across(all_of(c(agg_dims, "sector")))) %>%
    summarise(value = sum(value, na.rm = TRUE), .groups = "drop_last") %>%
    mutate(
      total_region_year_val = sum(value, na.rm = TRUE),
      share = if_else(total_region_year_val == 0, 0, value / total_region_year_val)
    ) %>%
    ungroup() %>%
    select(-total_region_year_val)

  write_csv(df_shares_agg, shares_agg_file)
  cat(sprintf("Saved aggregated sector shares to: %s\n", shares_agg_file))
}

# -----------------------------------------------------------------------------
# Execute for the selected models
# -----------------------------------------------------------------------------

walk(models, ~ process_shares(file.path("eumfatopdown", .x), is_steel = (.x == "steel")))


# -----------------------------------------------------------------------------
# STEP 2: Apply shares to trade from REMIND-MFA
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Function to Convert REMIND-MFA Trade Files into EU-MFA Format
# -----------------------------------------------------------------------------
convert_trade_data <- function(model_name,
                               remind_folder = file.path("remindmfa", paste0(model_name, "_trades")),
                               eumfa_folder  = file.path("eumfatopdown", model_name),
                               config_path   = "config.yml") {

  cat(sprintf("\n=== Processing Trade Conversion for Model: %s ===\n", model_name))

  # 1. Load Configuration File
  config <- read_yaml(config_path)

  # Find REMIND-MFA vs EU-MFA mapping for this model
  remind_corr_list <- keep(config$correspondence_remindmfa_eumfa, ~ .x$model == model_name)

  if (length(remind_corr_list) == 0) {
    cat(sprintf("Skipping %s: No 'correspondence_remindmfa_eumfa' section found in %s\n", model_name, config_path))
    return(NULL)
  }

  remind_corr <- remind_corr_list[[1]]

  # Parse Sector/Good mapping (handles both 'remindmfa_good' and 'remindmfa_sector')
  sector_corr <- map_dfr(remind_corr$sector_correspondence, function(x) {
    good_val <- if (!is.null(x$remindmfa_good)) x$remindmfa_good else x$remindmfa_sector
    tibble(
      eumfa_sector   = x$eumfa_sector,
      remindmfa_good = good_val
    )
  })

  # Parse Region mapping
  region_corr <- map_dfr(remind_corr$region_correspondence, function(x) {
    regions <- if (is.list(x$eumfa_regions)) unlist(x$eumfa_regions) else x$eumfa_regions
    tibble(
      eumfa_region     = regions,
      remindmfa_region = x$remindmfa_region
    )
  })

  # 2. Read Shares Files from EU-MFA
  shares_agg_path <- file.path(eumfa_folder, "FinalDemand_shares_agg.csv")
  shares_det_path <- file.path(eumfa_folder, "FinalDemand_shares.csv")

  if (!file.exists(shares_agg_path) || !file.exists(shares_det_path)) {
    cat(sprintf("Skipping %s: Shares files not found in %s\n", model_name, eumfa_folder))
    return(NULL)
  }

  shares_agg <- read_csv(shares_agg_path, show_col_types = FALSE)
  shares_det <- read_csv(shares_det_path, show_col_types = FALSE)

  # Columns to retain in output (excluding 'value', 'share' and 'share_in_sector')
  product_cols <- setdiff(names(shares_det), c("value", "share", "share_in_sector"))

  # ---------------------------------------------------------------------------
  # Task A: Convert Goods Trade Files (ExportNewGoods & ImportNewGoods)
  # ---------------------------------------------------------------------------
  # REMIND value per good (= sector group) x product share within the sector group.
  process_goods_file <- function(remind_filename, output_filename) {
    remind_path <- file.path(remind_folder, remind_filename)
    if (!file.exists(remind_path)) return(NULL)

    remind_data <- read_csv(remind_path, show_col_types = FALSE) %>%
      rename(time = Time, region = Region, good = Good, remind_val = value) %>%
      mutate(remind_val = remind_val * remind_unit_factor)

    new_goods <- remind_data %>%
      inner_join(region_corr, by = c("region" = "remindmfa_region"), relationship = "many-to-many") %>%
      inner_join(sector_corr, by = c("good" = "remindmfa_good"), relationship = "many-to-many") %>%
      inner_join(
        shares_det,
        by = c("eumfa_region" = "region", "time" = "time", "eumfa_sector" = "sector"),
        relationship = "many-to-many"
      ) %>%
      mutate(value = remind_val * share, region = eumfa_region, sector = eumfa_sector) %>%
      select(all_of(c(product_cols, "value")))

    write_csv(new_goods, file.path(eumfa_folder, output_filename))
    cat(sprintf("Saved: %s\n", file.path(eumfa_folder, output_filename)))
  }

  process_goods_file("good_market__exports.csv", "ExportNewGoods.csv")
  process_goods_file("imports__good_market.csv", "ImportNewGoods.csv")

  # ---------------------------------------------------------------------------
  # Task B: Convert IP Trade Files (ExportNewProducts & ImportNewProducts)
  # ---------------------------------------------------------------------------
  process_ip_file <- function(remind_filename, output_filename) {
    remind_path <- file.path(remind_folder, remind_filename)
    if (!file.exists(remind_path)) return(NULL)

    remind_ip <- read_csv(remind_path, show_col_types = FALSE) %>%
      rename(time = Time, region = Region, remind_val = value) %>%
      mutate(remind_val = remind_val * remind_unit_factor)

    # Step 1: Disaggregate IP total trades into sectors using FinalDemand_shares_agg
    ip_sector_level <- remind_ip %>%
      inner_join(region_corr, by = c("region" = "remindmfa_region"), relationship = "many-to-many") %>%
      inner_join(
        shares_agg,
        by = c("eumfa_region" = "region", "time" = "time"),
        relationship = "many-to-many"
      ) %>%
      mutate(sector_value = remind_val * share) %>%
      select(eumfa_region, time, sector, element, sector_value)

    # Step 2: Disaggregate sector trades into products/polymers.
    # FIX: use the product share within the SECTOR (share_in_sector), not the share within
    # the sector group (share) - the sector share has already been applied in step 1.
    new_products <- ip_sector_level %>%
      inner_join(
        shares_det,
        by = c("eumfa_region" = "region", "time" = "time", "sector" = "sector", "element" = "element"),
        relationship = "many-to-many"
      ) %>%
      mutate(value = sector_value * share_in_sector, region = eumfa_region) %>%
      select(all_of(c(product_cols, "value")))

    write_csv(new_products, file.path(eumfa_folder, output_filename))
    cat(sprintf("Saved: %s\n", file.path(eumfa_folder, output_filename)))
  }

  process_ip_file("ip_market__exports.csv", "ExportNewProducts.csv")
  process_ip_file("imports__ip_market.csv", "ImportNewProducts.csv")
}

# -----------------------------------------------------------------------------
# Execute Script
# -----------------------------------------------------------------------------
walk(models, ~ convert_trade_data(.x, config_path = "config.yml"))
