# © 2026 Wuppertal Institut für Klima, Umwelt, Energie gGmbH
#
# SPDX-License-Identifier: AGPL-3.0-or-later

library(yaml)
library(dplyr)
library(tidyr)
library(readr)
library(purrr)
library(zoo)

# Automatically set working directory to the directory containing this script
setwd(dirname(rstudioapi::getActiveDocumentContext()$path))

# -----------------------------------------------------------------------------
# STEP 1: Load Configuration and Calculate Growth Rates from Source Data
# -----------------------------------------------------------------------------

# 1. Load YAML configuration file
config <- read_yaml("config.yml")

# 2. Extract configuration entries
macro_reqs  <- config$opengem$extract_from_macro
sector_reqs <- config$opengem$extract_from_sector

# Helper function to read semicolon-delimited CSVs safely
read_gem_csv <- function(filepath) {
  read_delim(filepath, delim = ";", show_col_types = FALSE) %>%
    rename_with(tolower)
}

macro_df  <- read_gem_csv("opengem/MACRO_BASE.csv")
sector_df <- read_gem_csv("opengem/SECTOR_BASE.csv")

# 3. Filter and extract records defined in config

# Filter MACRO data
extracted_macro <- map_dfr(macro_reqs, function(req) {
  macro_df %>%
    filter(
      variable == req$variable,
      region   == req$region
    ) %>%
    mutate(sector = NA_character_) # Ensure sector column exists (empty)
})

# Filter SECTOR data
extracted_sector <- map_dfr(sector_reqs, function(req) {
  sector_df %>%
    filter(
      variable == req$variable,
      sector   == req$sector,
      region   == req$region
    )
})

# Combine extracted macro and sector data
combined_extracted <- bind_rows(extracted_macro, extracted_sector)

# 4. Reshape, interpolate annual years (2017 to 2050), and compute growth rates

# Identify year columns present in the input files (e.g., 2017, 2025, 2030, ...)
year_cols <- setdiff(names(combined_extracted), c("variable", "sector", "region"))

growth_rates_df <- combined_extracted %>%
  # Pivot to long format to handle year time-series
  pivot_longer(
    cols = all_of(year_cols),
    names_to = "year",
    values_to = "value"
  ) %>%
  mutate(
    year = as.integer(year),
    value = as.numeric(value)
  ) %>%
  # Group by variable, sector, and region to interpolate and calculate growth rates per series
  group_by(variable, sector, region) %>%
  # Create a complete sequence of annual years from 2017 to 2050
  complete(year = 2017:2050) %>%
  # Linear interpolation for missing intermediate years
  mutate(value = na.approx(value, x = year, rule = 2)) %>%
  # Compute year-over-year percentage growth rate: (Value_t - Value_{t-1}) / Value_{t-1}
  mutate(growth_rate = (value - lag(value)) / lag(value)) %>%
  # Filter to 2017:2050 range (2017 growth rate will be NA as there is no 2016 baseline)
  filter(year >= 2017 & year <= 2050) %>%
  ungroup() %>%
  # Format final output schema
  select(variable, sector, region, year, growth_rate) %>%
  mutate(sector = ifelse(is.na(sector), "", sector))

# 5. Export calculated growth rates to CSV
write_csv(growth_rates_df, "eumfatopdown/extracted_growth_rates.csv", na = "")

cat("Successfully extracted variables and exported growth rates to 'extracted_growth_rates.csv'\n")


# -----------------------------------------------------------------------------
# STEP 2: Process Model Correspondences & Merge Growth Rates
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# 1. Load Files
# -----------------------------------------------------------------------------

# Load pre-calculated growth rates (comma-separated CSV)
growth_rates <- read_csv("eumfatopdown/extracted_growth_rates.csv", show_col_types = FALSE) %>%
  mutate(
    year = as.integer(year),
    sector = ifelse(is.na(sector) | sector == "", NA_character_, sector)
  )

# Helper function to process each model (steel, plastics)
merge_model_growth_rates <- function(model_name, empty_template_file, output_dir) {
  
  # ---------------------------------------------------------------------------
  # 2. Extract Correspondences from YAML for this Model
  # ---------------------------------------------------------------------------
  model_cfg <- keep(config$correspondence_opengem_eumfa, ~ .x$model == model_name)[[1]]
  
  # Map sector correspondences
  sector_map <- map_dfr(model_cfg$sector_correspondence, function(x) {
    tibble(
      eumfa_sector     = x$eumfa_sector,
      opengem_sector   = ifelse(is.null(x$opengem_sector), NA_character_, x$opengem_sector),
      opengem_variable = x$opengem_variable
    )
  })
  
  # Map region correspondences
  region_map <- map_dfr(model_cfg$region_correspondence, function(x) {
    tibble(
      eumfa_region   = x$eumfa_regions,
      opengem_region = x$opengem_region
    )
  })
  
  # Build full cross-mapping lookup table with corresponding growth rates
  lookup_table <- sector_map %>%
    cross_join(region_map) %>%
    left_join(
      growth_rates,
      by = c(
        "opengem_variable" = "variable",
        "opengem_sector"   = "sector",
        "opengem_region"   = "region"
      ),
      relationship = "many-to-many"
    ) %>%
    select(eumfa_sector, eumfa_region, year, growth_rate)
  
  # ---------------------------------------------------------------------------
  # 3. Read Template & Merge Growth Rates
  # ---------------------------------------------------------------------------
  template_df <- read_delim(empty_template_file, delim = ";", show_col_types = FALSE)
  
  merged_df <- template_df %>%
    left_join(
      lookup_table,
      by = c(
        "sector" = "eumfa_sector",
        "region" = "eumfa_region",
        "time"   = "year"
      )
    ) %>%
    rename(value = growth_rate) # Populate new 'value' column
  
  # ---------------------------------------------------------------------------
  # 4. Save Output File
  # ---------------------------------------------------------------------------
  if (!dir.exists(output_dir)) {
    dir.create(output_dir, recursive = TRUE)
  }
  
  output_file_path <- file.path(output_dir, "growth_rate.csv")
  write_delim(merged_df, output_file_path, delim = ";", na = "")
  
  cat(sprintf("Saved successfully: %s\n", output_file_path))
}

# -----------------------------------------------------------------------------
# Execute for Steel and Plastics
# -----------------------------------------------------------------------------

# Process Steel
merge_model_growth_rates(
  model_name          = "steel",
  empty_template_file = "eumfatopdown/steel/growth_rate_empty_steel.csv",
  output_dir          = "eumfatopdown/steel"
)

# Process Plastics
merge_model_growth_rates(
  model_name          = "plastics",
  empty_template_file = "eumfatopdown/plastics/growth_rate_empty_plastics.csv",
  output_dir          = "eumfatopdown/plastics"
)


# -----------------------------------------------------------------------------
# STEP 3: Build past+future Final Demand vectors
# -----------------------------------------------------------------------------

build_final_demand <- function(folder_path) {
  
  # File paths
  past_path   <- file.path(folder_path, "FinalDemand_past.csv")
  start_path  <- file.path(folder_path, "start_value.csv")
  growth_path <- file.path(folder_path, "growth_rate.csv")
  output_path <- file.path(folder_path, "FinalDemand.csv")
  
  # Load files
  fd_past      <- read_csv(past_path, show_col_types = FALSE) %>% mutate(time = as.integer(time))
  start_val    <- read_csv(start_path, show_col_types = FALSE) %>% mutate(time = as.integer(time))
  growth_rates <- read_delim(growth_path, delim = ";", show_col_types = FALSE) %>% mutate(time = as.integer(time))
  
  # Identify baseline start year (e.g., 2023)
  start_year  <- min(start_val$time, na.rm = TRUE)
  future_years <- start_year:max(growth_rates$time, na.rm = TRUE)
  
  # 1. Past Data (Strictly before start_year)
  past_data <- fd_past %>%
    filter(time < start_year)
  
  # Identify dimension columns excluding 'time', 'value', and 'element' for join flexibility
  dimension_cols <- setdiff(names(start_val), c("time", "value", "element"))
  
  # 2. Build Future Sequence (Expand start_value for all future years)
  future_grid <- start_val %>%
    select(-time) %>%
    rename(start_value = value) %>%
    cross_join(tibble(time = future_years))
  
  # 3. Join Growth Rates & Compound Values Forward
  future_data <- future_grid %>%
    left_join(
      growth_rates %>% select(all_of(c(dimension_cols, "time", "value"))) %>% rename(growth_rate = value),
      by = c(dimension_cols, "time")
    ) %>%
    group_by(across(all_of(c(dimension_cols, "element")))) %>%
    arrange(time, .by_group = TRUE) %>%
    mutate(
      # Replace NA growth rates with 0
      growth_rate = ifelse(is.na(growth_rate), 0, growth_rate),
      # Set growth rate at start_year to 0 (since baseline year equals start_value)
      growth_factor = ifelse(time == start_year, 0, growth_rate),
      # Calculate compounded values
      value = start_value * cumprod(1 + growth_factor)
    ) %>%
    ungroup() %>%
    select(all_of(names(start_val))) # Keep exact original column structure
  
  # 4. Combine Past and Future Data & Save
  final_demand <- bind_rows(past_data, future_data) %>%
    arrange(across(all_of(c(dimension_cols, "element", "time"))))
  
  write_csv(final_demand, output_path)
  cat(sprintf("Successfully generated updated FinalDemand.csv in: %s\n", folder_path))
}

# Execute for both Steel and Plastics
target_folders <- c("eumfatopdown/steel", "eumfatopdown/plastics")
walk(target_folders, build_final_demand)