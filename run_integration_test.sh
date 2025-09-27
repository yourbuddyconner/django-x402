#!/bin/bash
# Script to run the Anvil integration test with proper environment setup

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Setting up environment for Anvil integration test...${NC}"

# Source the test environment variables
source test.env

# Check if docker-compose is available and start Anvil
if command -v docker-compose &> /dev/null; then
    echo -e "${GREEN}Starting Anvil fork...${NC}"
    docker-compose -f docker-compose.anvil.yml up -d
    
    # Wait a moment for Anvil to start
    sleep 2
    
    # Run the integration test
    echo -e "${GREEN}Running integration test...${NC}"
    pytest tests/test_integration_anvil.py::test_local_verify_and_settle_against_anvil -xvs
    
    # Stop Anvil
    echo -e "${YELLOW}Stopping Anvil...${NC}"
    docker-compose -f docker-compose.anvil.yml down
else
    echo -e "${RED}docker-compose not found. Running test without starting Anvil.${NC}"
    echo -e "${YELLOW}Make sure Anvil is running on port 8545!${NC}"
    
    # Run the test anyway
    pytest tests/test_integration_anvil.py::test_local_verify_and_settle_against_anvil -xvs
fi
